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

  if (app.ports && app.ports.watchJob) {
    app.ports.watchJob.subscribe((jobId) => {
      if (open.has(jobId)) return;
      const source = new EventSource(`/api/jobs/${jobId}/events`);
      open.set(jobId, source);

      source.onmessage = (event) => {
        try {
          app.ports.jobEvent.send(JSON.parse(event.data));
        } catch (err) {
          console.error("sleepmix: unparseable job event", err);
        }
      };

      source.onerror = () => {
        // The stream closes normally once a job reaches a terminal status, so
        // an error here is usually just that. Close rather than let the
        // browser reconnect to a finished job forever.
        source.close();
        open.delete(jobId);
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
