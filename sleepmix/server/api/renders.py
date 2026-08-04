"""``/api/renders`` — start a full mix, watch it, fetch the result.

A render takes minutes, so it is a job like separation is. The database row is
created up front with status ``queued`` so the UI has something to show
immediately and so the config that produced a given file is recorded even if
the render later fails.

Output lands in ``paths.data_dir()/renders``, not the working directory — the
server has no meaningful CWD.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...config import MixConfig
from ...paths import data_dir
from ...pipeline import run_pipeline
from ...progress import Cancelled

router = APIRouter(prefix="/api/renders", tags=["renders"])


class RenderRequest(BaseModel):
    song_id: str
    config: dict | None = None
    preset_id: str | None = None


def _renders_dir() -> str:
    path = os.path.join(str(data_dir()), "renders")
    os.makedirs(path, exist_ok=True)
    return path


def _abandon(store, render_id: str, output_path: str, status: str) -> None:
    """Record a render that produced nothing, and leave no partial file.

    Both failure paths go through here so the row can never be left at
    "running" and a half-written file can never masquerade as a finished
    render. Errors while cleaning up are swallowed deliberately: the original
    exception is the one worth propagating."""
    try:
        store.update_render(render_id, status=status)
    finally:
        try:
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass


@router.post("", status_code=202)
def start_render(body: RenderRequest, request: Request) -> dict:
    store = request.app.state.store
    song = store.get_song(body.song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    raw_config = body.config
    if raw_config is None and body.preset_id:
        preset = next((p for p in store.list_presets() if p["id"] == body.preset_id), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="No such preset")
        raw_config = preset["config"]

    try:
        config = MixConfig.from_dict(raw_config) if raw_config else MixConfig()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    render = store.add_render(song_id=body.song_id, config=raw_config or {},
                              path="", status="queued")
    output_path = os.path.join(_renders_dir(), f"{render['id']}.wav")
    store.update_render(render["id"], path=output_path)
    source = song["path"]

    def work(reporter, cancel) -> dict:
        store.update_render(render["id"], status="running")
        try:
            mix = run_pipeline(source, config, output_path,
                               reporter=reporter, cancel=cancel)
        except Cancelled:
            _abandon(store, render["id"], output_path, "cancelled")
            raise
        except Exception:
            # Genuine failure, not a cancellation. Classified by exception
            # type rather than by consulting ``cancel.cancelled`` — the token
            # can already be set when an unrelated failure fires before the
            # pipeline reaches its next check(), and the job manager itself
            # classifies by type, so this must match it or the render row and
            # the job row disagree about the same event.
            _abandon(store, render["id"], output_path, "failed")
            raise
        store.update_render(render["id"], status="done",
                            duration_min=mix.duration / 60.0)
        return {"render_id": render["id"], "path": output_path}

    job = request.app.state.jobs.submit("render", work, song_id=body.song_id)
    return {"job": job.as_event(), "render": store.get_render(render["id"])}


@router.get("")
def list_renders(request: Request) -> dict:
    return {"renders": request.app.state.store.list_renders()}


@router.get("/{render_id}")
def get_render(render_id: str, request: Request) -> dict:
    render = request.app.state.store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    return render


@router.get("/{render_id}/audio")
def get_render_audio(render_id: str, request: Request) -> FileResponse:
    render = request.app.state.store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    if render["status"] != "done" or not os.path.isfile(render["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"No audio for this render (status: {render['status']})")
    return FileResponse(render["path"], media_type="audio/wav",
                        filename=f"{render_id}.wav")


@router.delete("/{render_id}", status_code=204)
def delete_render(render_id: str, request: Request) -> Response:
    """Remove a render and its file.

    Refused while the render is still being produced: the pipeline would go on
    writing to a path nobody will look at, and the row it updates on completion
    would be gone. Cancel the job first — that path already deletes the partial
    file through ``_abandon``."""
    store = request.app.state.store
    render = store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    if render["status"] in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail="This render is still being produced — cancel it first.")
    path = render["path"]
    store.delete_render(render_id)
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        # The row is gone, which is what the caller asked for. A file we cannot
        # remove is a disk problem, not a reason to resurrect the record.
        pass
    return Response(status_code=204)
