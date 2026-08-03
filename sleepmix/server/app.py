"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can build an isolated
instance per test — the store and the app-data directory are per-instance
state, and a shared global would leak between tests.

Routers live in ``api/``, one module per resource. This module wires them
together and owns process-lifetime state on ``app.state``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

import sleepmix

from .api import schema, songs
from .store import Store


def create_app(store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store()
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="sleepmix", version=sleepmix.__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": sleepmix.__version__}

    app.include_router(schema.router)
    app.include_router(songs.router)
    return app
