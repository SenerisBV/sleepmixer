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
        # Called for the ValueError, not the value: what gets stored is the raw
        # dict, and this is the only thing standing between a bad config and a
        # preset that fails much later, at render time, with the connection to
        # the offending value long gone. Bound rather than discarded so a
        # "remove the unused call" cleanup cannot silently delete the 400 path.
        _validated = MixConfig.from_dict(body.config)  # noqa: F841
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        return request.app.state.store.add_preset(body.name, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/{preset_id}")
def update_preset(preset_id: str, body: PresetRequest, request: Request) -> dict:
    """Rename a preset, save over it, or both.

    Validated exactly as ``create_preset`` is, and for the same reason: a
    preset that could never render must fail here, not at render time with the
    connection to the offending value long gone."""
    try:
        _validated = MixConfig.from_dict(body.config)  # noqa: F841
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        updated = request.app.state.store.update_preset(
            preset_id, body.name, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="No such preset")
    return updated


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str, request: Request) -> Response:
    if not request.app.state.store.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="No such preset")
    return Response(status_code=204)
