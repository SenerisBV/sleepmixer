"""``/api/presets`` — named config snapshots.

A preset is validated before it is stored. Saving one that could never render
just moves the failure to whenever someone tries to use it, by which point the
connection to the bad value has been lost.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ...config import MixConfig

router = APIRouter(prefix="/api/presets", tags=["presets"])


class PresetRequest(BaseModel):
    name: str
    config: dict


@router.get("")
def list_presets(request: Request) -> dict:
    return {"presets": request.app.state.store.list_presets()}


@router.post("", status_code=201)
def create_preset(body: PresetRequest, request: Request) -> dict:
    try:
        MixConfig.from_dict(body.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        return request.app.state.store.add_preset(body.name, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str, request: Request) -> Response:
    if not request.app.state.store.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="No such preset")
    return Response(status_code=204)
