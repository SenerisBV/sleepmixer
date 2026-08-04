"""``/api/jobs`` — watch and cancel background work.

Polling and streaming both live here. The stream is the one the UI uses; the
polling route exists because it is far easier to test and to reach for from a
shell.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..jobs import TERMINAL_STATUSES
from ..renders import abandon_render

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_HEARTBEAT_SECONDS = 15.0


@router.get("")
def list_jobs(request: Request) -> dict:
    return {"jobs": [job.as_event() for job in request.app.state.jobs.list()]}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return job.as_event()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    """Stop a job, and settle anything it was going to write but now will not.

    The settling is here rather than in the work function because for one case
    the work function never runs. ``JobManager._run`` short-circuits without
    calling it when the token is already set — deliberate, and what stops a
    cancelled separation from starting Demucs anyway — so a render cancelled
    while it was still *queued* had nothing to write its row: the job read
    "cancelled" while the row read "queued" forever, and ``DELETE
    /api/renders/{id}`` refuses anything at "queued", so the row could not be
    removed either. The queue screen and the renders screen, one click apart,
    disagreed about the same render with no way to resolve it.

    **Only when the job came back terminal.** A *running* render settles its
    own row through ``work``'s ``except Cancelled``, and writing it from this
    request thread as well would race the worker — the case that would hurt is
    a render finishing a moment after the token was set, where this would put
    "cancelled" over a row the pipeline had just marked "done". ``cancel`` ends
    a queued job synchronously and leaves a running one alone, so the status
    read back here is exactly the test for "the work function will never run".

    Not gated on ``cancelled`` being True: a second cancel of an
    already-cancelled render re-settles a row that is already settled, which
    ``abandon_render`` is idempotent for, and that makes this the one place a
    row stranded by any earlier version of this code can still be cleared.
    """
    manager = request.app.state.jobs
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")

    # Held across the cancel rather than re-fetched after it. `JobManager`
    # mutates its jobs in place, so this reference reflects the cancel — and it
    # still exists if cancelling was what tipped this job out of the bounded
    # set of terminal ones the manager keeps. Re-fetching would answer with a
    # `job` of null in that case, which the client's decoder refuses.
    cancelled = manager.cancel(job_id)

    if job.render_id and job.status == "cancelled":
        store = request.app.state.store
        render = store.get_render(job.render_id)
        if render is not None:
            abandon_render(store, job.render_id, render["path"], "cancelled")

    return {"cancelled": cancelled, "job": job.as_event()}


@router.get("/{job_id}/events")
async def stream_job(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events for one job, closing once it reaches a terminal state.

    SSE rather than WebSockets because progress only travels one way and SSE
    reconnects by itself. Elm cannot open an EventSource, so a small JS port
    owns the connection and forwards parsed events in — which is why the
    payload stays a plain JSON object rather than a bespoke framing."""
    manager = request.app.state.jobs
    # subscribe() does an unguarded queue.put_nowait for the late-subscriber
    # snapshot path; that is only safe because subscribe() runs on the event
    # loop thread, same as this coroutine. Do not move this call onto a
    # worker thread or a run_in_threadpool — that would touch the asyncio
    # queue from off the loop and corrupt it.
    queue = manager.subscribe(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No such job")

    async def events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(),
                                                   timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Comment frame: keeps proxies and browsers from timing out
                    # a long render that has not emitted lately.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event["status"] in TERMINAL_STATUSES:
                    return
        finally:
            manager.unsubscribe(job_id, queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
