"""``/api/jobs`` — watch and cancel background work.

Polling and streaming both live here. The stream is the one the UI uses; the
polling route exists because it is far easier to test and to reach for from a
shell.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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
