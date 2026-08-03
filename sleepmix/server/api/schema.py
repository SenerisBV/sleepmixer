"""``/api/schema`` — config field metadata.

The UI generates its controls from this rather than hard-coding them, so a new
config parameter appears in the interface without a frontend change.
"""
from __future__ import annotations

from fastapi import APIRouter

from ...config import config_schema

router = APIRouter(prefix="/api", tags=["schema"])


@router.get("/schema")
def get_schema() -> dict:
    return config_schema()
