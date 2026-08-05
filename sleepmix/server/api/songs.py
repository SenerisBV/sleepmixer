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

from ...analysis import find_loop
from ...audio import load_audio
from ...config import LoopConfig
from ...paths import cache_dir
from ...peaks import compute_peaks
from ...progress import Cancelled
from ...separation import invalidate_cache
from ...separation_process import run_separation

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


@router.get("/{song_id}/loop")
def get_loop(
    song_id: str,
    request: Request,
    start_s: float | None = None,
    end_s: float | None = None,
) -> dict:
    """The loop region a render would use, in seconds, plus the tempo estimate.

    Runs on the whole file rather than on separated stems, so it answers before
    separation and needs no warm session. Passing ``start_s``/``end_s`` echoes
    that region back with a tempo — which is what the UI does once you have
    dragged the handles, so the readout stays consistent with what a render
    would actually loop."""
    song = request.app.state.store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    buf = load_audio(song["path"])
    config = LoopConfig(start_s=start_s, end_s=end_s)
    point = find_loop(buf, config)
    return {
        "start_s": point.start / buf.sr,
        "end_s": point.end / buf.sr,
        "tempo": point.tempo,
    }


@router.post("/{song_id}/separate", status_code=202)
def separate_song(song_id: str, request: Request, force: bool = False) -> dict:
    """Kick off stem separation as a background job.

    ``force`` deletes the cached result first. That matters because the cache
    key says nothing about whether Demucs was importable: without it, a song
    separated before the ``separation`` extra was installed would keep
    reporting itself as a fallback."""
    store = request.app.state.store
    song = store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    # Idempotent for the case that matters: a page reload — or a second tab —
    # has no client-side memory of a separation already in flight, so without
    # this it would submit a second job behind the first rather than attach to
    # it. Checked even when force=true: a forced re-separation invalidates the
    # cache, and doing that underneath a separation that is already reading
    # from it is worse than making the caller wait for, or explicitly cancel,
    # the one already running.
    existing = next(
        (job for job in request.app.state.jobs.list()
         if job.kind == "separate" and job.song_id == song_id
         and job.status in ("queued", "running")),
        None)
    if existing is not None:
        return existing.as_event()

    path = song["path"]
    model = request.app.state.separation_model
    sessions = request.app.state.sessions

    def work(reporter, cancel) -> dict:
        # Set once the job actually starts, not before submitting it. A job
        # cancelled while still queued never reaches this closure at all (the
        # job manager stops it before calling in), so setting "running" here
        # rather than in the route means a song whose separation was cancelled
        # before it started is left exactly as it was — not stuck at
        # "running" forever with nothing left to ever change it back.
        store.update_song(song_id, separation_status="running", separation_reason=None)
        reporter.emit("separate", "Separating stems…", 0.0)
        try:
            # Before the invalidation, not after: a cancel that lands in this
            # window would otherwise delete the cached stems on its way out and
            # leave the song with nothing, having been asked to stop.
            cancel.check()
            if force:
                invalidate_cache(path, model, cache_dir=str(cache_dir()))
                # The row and the cache are two records of one fact, and this
                # is the only line in the codebase that can make them
                # disagree. Deleting the stems while `songs.stems` still
                # lists them leaves a row that claims a separation nothing on
                # disk can honour — and every gate into the mixer reads that
                # field rather than the cache, so the claim is believed.
                #
                # Cleared HERE rather than in the two handlers below, because
                # the window opens at the deletion and not at the exception:
                # from this line until the final update_song, the honest
                # answer to "what stems does this song have" is none. Both
                # exits — Cancelled and any other failure — inherit that for
                # free, and a success overwrites it with the real list.
                #
                # What the alternative costs is worth naming, since it is the
                # thing this branch made reachable: a cancelled forced retry
                # left a row reading "not separated" WITH a stem list and an
                # enabled Open-the-mixer. Opening it runs `separation.separate
                # ()` in-process inside SessionRegistry's per-song lock — no
                # job, no queue row, no Cancel — and then caches stems the
                # mixer's rows were not built from, so `plan_stem_configs`
                # matches none of them and every gain, send and decay on
                # screen is silently replaced by a default.
                store.update_song(song_id, stems=[])
            result = run_separation(path, model, str(cache_dir()),
                                     reporter=reporter, cancel=cancel)
        except Cancelled:
            # Nothing was produced, so the honest state is the one we started
            # from — not "failed", which would imply the song is broken.
            store.update_song(song_id, separation_status="pending",
                              separation_reason=None)
            raise
        except Exception as exc:
            # Without this the row stays "running" for good, and force=true
            # cannot rescue it because it re-enters this same closure.
            store.update_song(song_id, separation_status="failed",
                              separation_reason=f"{type(exc).__name__}: {exc}")
            raise
        status = "fallback" if result.fallback_reason else "done"
        store.update_song(song_id,
                          separation_status=status,
                          separation_reason=result.fallback_reason,
                          stems=sorted(result.stems))
        # The song's audio changed shape underneath any warm session.
        sessions.discard(song_id)
        reporter.emit("separate", "Done", 1.0)
        return {"status": status, "stems": sorted(result.stems)}

    job = request.app.state.jobs.submit("separate", work, song_id=song_id)
    return job.as_event()
