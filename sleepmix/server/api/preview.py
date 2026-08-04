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
from ...config import MixConfig
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

    session = request.app.state.sessions.get(body.song_id, song["path"], config)
    window = render_window(session, body.progress,
                           stems=body.stems, reverb=body.reverb)
    return Response(content=encode_wav(window), media_type="audio/wav")
