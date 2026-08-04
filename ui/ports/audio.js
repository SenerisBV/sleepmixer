// Web Audio for previews. Fetches, decodes, plays, reports. Decides nothing.
//
// Elm cannot do any of this: ports carry JSON, so audio bytes cannot cross,
// and there is no Web Audio binding. What Elm *does* own is the decision of
// when to ask — see ui/src/Preview.elm — because that is the part that can be
// tested. This module holds two pieces of state, the playing source and the
// in-flight fetch, and nothing else. A queue here would be a bug.
//
// Swapping is scheduled at the next loop boundary rather than immediate, so
// changing a decay setting mid-playback lands on a musical seam instead of a
// click.

export function wire(app) {
  let context = null;
  let playing = null; // { source, startedAt, duration }
  let inFlight = null; // AbortController

  const ensureContext = () => {
    if (context === null) {
      context = new (window.AudioContext || window.webkitAudioContext)();
    }
    // Browsers start the context suspended until a user gesture; every
    // request follows a click or a drag, so resuming here is safe.
    if (context.state === "suspended") context.resume();
    return context;
  };

  const nextBoundary = (ctx) => {
    if (playing === null) return ctx.currentTime;
    const elapsed = ctx.currentTime - playing.startedAt;
    const cycles = Math.ceil(elapsed / playing.duration);
    return playing.startedAt + cycles * playing.duration;
  };

  const play = (ctx, buffer) => {
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    source.connect(ctx.destination);

    const at = nextBoundary(ctx);
    source.start(at);
    if (playing !== null) playing.source.stop(at);
    playing = { source, startedAt: at, duration: buffer.duration };
  };

  const stop = () => {
    if (playing !== null) {
      try {
        playing.source.stop();
      } catch (err) {
        // Already stopped; harmless.
      }
      playing = null;
    }
  };

  if (app.ports && app.ports.requestPreview) {
    app.ports.requestPreview.subscribe(async (params) => {
      if (inFlight !== null) inFlight.abort();
      inFlight = new AbortController();
      const controller = inFlight;

      try {
        const response = await fetch("/api/preview", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(params),
          signal: controller.signal,
        });
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(`server answered ${response.status}: ${detail}`);
        }
        const bytes = await response.arrayBuffer();
        const ctx = ensureContext();
        const buffer = await ctx.decodeAudioData(bytes);
        if (controller !== inFlight) return; // superseded while decoding
        play(ctx, buffer);
        app.ports.previewReady.send({ durationS: buffer.duration });
      } catch (err) {
        if (err.name === "AbortError") return; // Elm already moved on
        app.ports.previewFailed.send(String(err.message || err));
      } finally {
        if (controller === inFlight) inFlight = null;
      }
    });
  }

  if (app.ports && app.ports.stopPreview) {
    app.ports.stopPreview.subscribe(() => {
      if (inFlight !== null) {
        inFlight.abort();
        inFlight = null;
      }
      stop();
    });
  }
}
