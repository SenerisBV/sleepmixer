"""``/api/config`` — the server's own starting point, as values.

Separate from ``/api/schema``, which describes the *shape* of a config: what
fields exist, their types, bounds and choices. That description deliberately
says nothing about list-typed fields, so it cannot express ``MixConfig``'s
curated per-stem list — and a mixer built from the schema alone starts every
stem identical, which is not where the CLI starts. This route closes that by
publishing the values themselves.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from ...config import MixConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/default")
def default_config() -> dict:
    return asdict(MixConfig())
