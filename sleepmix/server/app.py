"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can build an isolated
instance per test — the store and the app-data directory are per-instance
state, and a shared global would leak between tests.

Routers live in ``api/``, one module per resource. This module wires them
together and owns process-lifetime state on ``app.state``.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import sleepmix

from ..config import MixConfig
from .api import jobs as jobs_api
from .api import preview, renders, schema, songs
from .jobs import JobManager
from .sessions import SessionRegistry
from .store import Store
from .warmup import is_warm, warm_analysis


def create_app(store: Store | None = None) -> FastAPI:
    static_dir = Path(__file__).resolve().parent.parent / "static"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Close only what this lifespan opened. An injected store belongs to
        # the caller: closing it on shutdown would leave a caller-held Store
        # with a dead connection, and a second TestClient context over the same
        # app would rebind that closed connection and raise ProgrammingError.
        owned = store is None
        app.state.store = Store() if owned else store
        # The manager needs the running loop so it can marshal progress events
        # from the worker thread into subscriber queues.
        app.state.jobs = JobManager(loop=asyncio.get_running_loop())
        app.state.sessions = SessionRegistry()
        app.state.separation_model = MixConfig().separation_model
        # Off the event loop: warming blocks for minutes on a cold numba cache,
        # and the UI should be able to render its shell meanwhile.
        app.state.warm_task = asyncio.create_task(asyncio.to_thread(warm_analysis))
        try:
            yield
        finally:
            # Abandons the await, not the thread: asyncio.to_thread runs on a
            # non-cancellable executor, so a warm-up already in flight finishes
            # on its own. Acceptable here — it is bounded by one beat_track call
            # and the worker is not a daemon holding the process open.
            app.state.warm_task.cancel()
            app.state.jobs.shutdown()
            app.state.sessions.clear()
            if owned:
                app.state.store.close()

    app = FastAPI(title="sleepmix", version=sleepmix.__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": sleepmix.__version__, "warm": is_warm()}

    app.include_router(schema.router)
    app.include_router(songs.router)
    app.include_router(jobs_api.router)
    app.include_router(preview.router)
    app.include_router(renders.router)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
