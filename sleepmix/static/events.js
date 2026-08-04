// EventSource bridge.
//
// Elm cannot open an EventSource — elm/http has no server-sent-events support
// — so this module owns the connection and forwards parsed events inward. It
// stays deliberately thin: no state beyond the open connections, no decisions,
// no retry policy of its own beyond the browser's own reconnection.
//
// A later change adds the audio engine as a sibling module. Both keep the same
// shape: Elm sends parameters out, JavaScript sends outcomes back, and nothing
// but JSON crosses the boundary.

export function wire(app) {
  const open = new Map();

  // A job id is server-generated hex today, so nothing here is exploitable —
  // but a raw id interpolated into a path is the pattern that stops being safe
  // the moment something less controlled goes through it. Request.elm builds
  // its URLs with Url.Builder for the same reason.
  const eventsUrl = (jobId) => `/api/jobs/${encodeURIComponent(jobId)}/events`;

  // The one decision this module does not make is whether a closed stream is a
  // problem: the browser fires `onerror` identically for a job finishing, a
  // network blip, a server restart and an unknown job id. Elm knows whether it
  // has already seen a terminal event, so Elm decides. Here we only report
  // that the connection is gone — and only while we still own it, so a stream
  // Elm has already told us to drop stays silent.
  const lost = (jobId, source) => {
    if (!open.has(jobId)) return;
    source.close();
    open.delete(jobId);
    if (app.ports && app.ports.jobStreamFailed) {
      app.ports.jobStreamFailed.send(jobId);
    }
  };

  if (app.ports && app.ports.watchJob) {
    app.ports.watchJob.subscribe((jobId) => {
      if (open.has(jobId)) return;
      const source = new EventSource(eventsUrl(jobId));
      open.set(jobId, source);

      source.onmessage = (event) => {
        try {
          app.ports.jobEvent.send(JSON.parse(event.data));
        } catch (err) {
          // Nothing further can be trusted from a stream sending frames we
          // cannot parse, and leaving it open would keep Elm waiting on
          // progress that will never arrive readably.
          console.error("sleepmix: unparseable job event", err);
          lost(jobId, source);
        }
      };

      source.onerror = () => {
        lost(jobId, source);
      };
    });
  }

  if (app.ports && app.ports.stopWatchingJob) {
    app.ports.stopWatchingJob.subscribe((jobId) => {
      const source = open.get(jobId);
      if (source) {
        source.close();
        open.delete(jobId);
      }
    });
  }
}
