"""Background work with live progress and cooperative cancellation.

Separating a song takes ~10 seconds and rendering a mix takes minutes. Neither
can happen inside a request, so both run on a worker thread and the client
watches through :mod:`sleepmix.server.api.jobs`.

One worker, deliberately. Renders are CPU-bound numpy over hundreds of loop
iterations; two at once would halve each other's speed and double peak memory,
on a tool one person uses at a time.

The manager knows nothing about audio. A job is any callable taking a
``ProgressReporter`` and a ``CancelToken`` and returning a JSON-ready dict.
"""
from __future__ import annotations

import asyncio
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..progress import Cancelled, CancelToken, ProgressEvent, ProgressReporter

JOB_STATUSES = ("queued", "running", "done", "cancelled", "failed")
# The statuses after which no further events can arrive. The SSE stream ends
# on these, so a status that belongs here and is missed would leave a stream
# running forever.
TERMINAL_STATUSES = ("done", "failed", "cancelled")

JobFn = Callable[[ProgressReporter, CancelToken], dict]


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    fraction: float = 0.0
    message: str = ""
    error: str | None = None
    result: dict | None = None
    song_id: str | None = None
    # The row this job is producing, for the kinds of job that produce one.
    # Only renders do today. Without it the only way to tell which render a job
    # belongs to is the song it came from and when it started, and that pairing
    # is wrong exactly when it matters: a render row left at "running" by a
    # restart has no job of its own, so it matches the *next* render of the same
    # song and offers a Cancel button that stops a different render.
    render_id: str | None = None
    created_at: str = ""

    def as_event(self) -> dict:
        return asdict(self)


class JobManager:
    """Runs jobs on a worker thread and fans progress out to subscribers."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None,
                 max_workers: int = 1, keep_terminal: int = 50) -> None:
        self._loop = loop
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="sleepmix-job")
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._keep_terminal = keep_terminal

    # -- lifecycle ------------------------------------------------------
    def submit(self, kind: str, fn: JobFn, song_id: str | None = None,
               render_id: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, song_id=song_id,
                  render_id=render_id,
                  created_at=datetime.now(timezone.utc).isoformat())
        token = CancelToken()
        with self._lock:
            self._jobs[job.id] = job
            self._tokens[job.id] = token
            self._subscribers.setdefault(job.id, [])
        self._pool.submit(self._run, job.id, fn, token)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(job_id)
            job = self._jobs.get(job_id)
        if token is None or job is None or job.status in TERMINAL_STATUSES:
            return False
        token.cancel()
        return True

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            for token in self._tokens.values():
                token.cancel()
        self._pool.shutdown(wait=wait)

    # -- subscriptions --------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue | None:
        """Get a queue of progress events for ``job_id``.

        A job that has already finished pushes its final state immediately, so
        a client connecting late sees an outcome instead of hanging."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            queue: asyncio.Queue = asyncio.Queue()
            self._subscribers.setdefault(job_id, []).append(queue)
            terminal = job.status in TERMINAL_STATUSES
            snapshot = job.as_event()
        if terminal:
            queue.put_nowait(snapshot)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self._subscribers.get(job_id, [])
            if queue in queues:
                queues.remove(queue)

    # -- internals ------------------------------------------------------
    def _run(self, job_id: str, fn: JobFn, token: CancelToken) -> None:
        if token.cancelled:
            # Cancelled while it was still sitting in the pool's queue. Without
            # this it would start anyway and only stop at the work function's
            # first check() — which for separation is the check that happens
            # before Demucs, so the cancel was invisible.
            self._update(job_id, status="cancelled", message="Cancelled")
            return
        self._update(job_id, status="running")
        reporter = ProgressReporter(lambda event: self._on_event(job_id, event))
        try:
            result = fn(reporter, token)
        except Cancelled:
            self._update(job_id, status="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
            self._update(job_id, status="failed",
                         error=f"{type(exc).__name__}: {exc}",
                         message="Failed")
            traceback.print_exc()
        else:
            self._update(job_id, status="done", fraction=1.0,
                         result=result, message="Done")

    def _on_event(self, job_id: str, event: ProgressEvent) -> None:
        self._update(job_id, fraction=event.fraction, message=event.message)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            snapshot = job.as_event()
            queues = list(self._subscribers.get(job_id, []))
            if job.status in TERMINAL_STATUSES:
                self._evict()
        for queue in queues:
            self._publish(queue, snapshot)

    def _evict(self) -> None:
        """Drop the oldest terminal jobs, keeping queued and running ones.

        Called with the lock held. ``_jobs`` is insertion-ordered, and a job's
        position never changes, so the oldest terminal job is the first one in
        iteration order — no sorting needed. Live jobs are never dropped
        however many there are: the queue screen's whole purpose is to say what
        is about to happen, and a dropped queued job makes it lie."""
        terminal = [jid for jid, j in self._jobs.items()
                    if j.status in TERMINAL_STATUSES]
        for jid in terminal[:max(0, len(terminal) - self._keep_terminal)]:
            self._jobs.pop(jid, None)
            self._tokens.pop(jid, None)
            self._subscribers.pop(jid, None)

    def _publish(self, queue: asyncio.Queue, snapshot: dict) -> None:
        """Hand a snapshot to a queue owned by the event loop.

        ``_update`` runs on the worker thread, so the put must be marshalled
        across; ``call_soon_threadsafe`` is the only safe way to touch an
        asyncio primitive from another thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, snapshot)
        except RuntimeError:
            pass  # loop shut down between the check and the call
