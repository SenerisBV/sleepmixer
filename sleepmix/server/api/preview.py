"""``/api/preview`` — hear one point in the decay arc, immediately.

``apply_decay`` is a pure function of progress: repetition four hundred does
not depend on the three hundred and ninety-nine before it. So auditioning the
point two thirds of the way through a twenty-five minute mix costs a single
loop iteration rather than rendering everything preceding it. The session
registry is what keeps that true from one request to the next.

Returns raw WAV bytes. Elm cannot carry binary over a port, so the browser-side
audio module fetches this directly and Elm only ever sends the parameters.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...audio import encode_wav
from ...config import MixConfig, NothingToRender
from ...preview import render_window

router = APIRouter(prefix="/api", tags=["preview"])


class PreviewRequest(BaseModel):
    song_id: str
    progress: float = Field(ge=0.0, le=1.0)
    stems: list[str] | None = None
    reverb: bool = True
    config: dict | None = None


@router.post("/preview")
def preview(body: PreviewRequest, request: Request) -> Response:
    song = request.app.state.store.get_song(body.song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    try:
        config = MixConfig.from_dict(body.config) if body.config else MixConfig()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Held for the whole render, not just the lookup. This route is a sync
    # ``def``, so FastAPI runs it in the threadpool and a scrubber drag puts
    # several of these on one ``RenderSession`` at once — where a concurrent
    # ``update_config`` would clear caches mid-render. See ``session_for``.
    try:
        with request.app.state.sessions.session_for(
                body.song_id, song["path"], config) as session:
            window = render_window(session, body.progress,
                                   stems=body.stems, reverb=body.reverb)
    except NothingToRender as exc:
        # A config that asks for nothing — every stem switched off, or a solo
        # naming only stems this render would drop. 400 with the reason rather
        # than 200 with a one-frame WAV: the browser cannot tell silence from
        # silence, so the only way the mixer can say *why* it went quiet is for
        # this to fail out loud. See ``preview.render_window``.
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(content=encode_wav(window), media_type="audio/wav")
