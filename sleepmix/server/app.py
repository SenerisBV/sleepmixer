"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can build an isolated
instance per test — the store and the app-data directory are per-instance
state, and a shared global would leak between tests.
"""
from __future__ import annotations

from fastapi import FastAPI

import sleepmix


def create_app() -> FastAPI:
    app = FastAPI(title="sleepmix", version=sleepmix.__version__)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": sleepmix.__version__}

    return app
