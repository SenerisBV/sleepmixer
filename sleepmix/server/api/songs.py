"""``/api/songs`` — the library's record of importable audio files.

Importing registers a *path*, it does not copy the file. This is a local tool
operating on the operator's own music; copying gigabytes into an app-data
directory would be surprising and wasteful. The cost is that a song can become
unavailable if the file moves, which is reported rather than raised.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...audio import load_audio
from ...peaks import compute_peaks

router = APIRouter(prefix="/api/songs", tags=["songs"])

MAX_PEAK_BUCKETS = 20000


class ImportRequest(BaseModel):
    path: str


@router.post("", status_code=201)
def import_song(body: ImportRequest, request: Request) -> dict:
    path = os.path.abspath(os.path.expanduser(body.path))
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        buf = load_audio(path)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad request
        raise HTTPException(
            status_code=400, detail=f"Could not read audio from {path}: {exc}")
    title = os.path.splitext(os.path.basename(path))[0]
    return request.app.state.store.add_song(
        path=path, title=title, duration_s=buf.duration, sample_rate=buf.sr)


@router.get("")
def list_songs(request: Request) -> dict:
    return {"songs": request.app.state.store.list_songs()}


@router.get("/{song_id}")
def get_song(song_id: str, request: Request) -> dict:
    song = request.app.state.store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    return song


@router.get("/{song_id}/peaks")
def get_peaks(
    song_id: str,
    request: Request,
    buckets: int = Query(default=2000, ge=1, le=MAX_PEAK_BUCKETS),
) -> dict:
    song = request.app.state.store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")
    buf = load_audio(song["path"])
    return {"peaks": compute_peaks(buf, buckets), "duration_s": buf.duration}
