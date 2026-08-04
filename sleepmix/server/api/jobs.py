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

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_TERMINAL = ("done", "failed", "cancelled")
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
    if request.app.state.jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="No such job")
    cancelled = request.app.state.jobs.cancel(job_id)
    return {"cancelled": cancelled, "job": request.app.state.jobs.get(job_id).as_event()}


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
                if event["status"] in _TERMINAL:
                    return
        finally:
            manager.unsubscribe(job_id, queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
