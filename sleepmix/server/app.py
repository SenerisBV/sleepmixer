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
from starlette.responses import PlainTextResponse

import sleepmix

from ..config import MixConfig
from .api import config as config_api
from .api import jobs as jobs_api
from .api import presets, preview, renders, schema, songs
from .jobs import JobManager
from .sessions import SessionRegistry
from .store import Store
from .warmup import is_warm, warm_analysis


#: Hosts accepted when the caller does not name any. Loopback in the three
#: spellings a browser can produce, plus ``testserver`` — the ``Host`` header
#: FastAPI's ``TestClient`` sends, which is why an allow-list was previously
#: deferred rather than added. Including it is a one-line answer to that.
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")


def _host_without_port(raw: str) -> str:
    """The host part of a ``Host`` header, lowercased, port and brackets gone.

    Three shapes to handle: ``name``/``name:port``, ``1.2.3.4``/``1.2.3.4:port``,
    and ``[::1]``/``[::1]:port``. Only the bracketed form may contain colons in
    the host itself, which is exactly what a naive ``split(":")[0]`` gets wrong.
    """
    raw = raw.strip().lower()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw[1:]
    return raw.split(":", 1)[0]


class _HostAllowList:
    """Reject requests whose ``Host`` is not one this server answers to.

    The cheapest real mitigation against DNS rebinding, which is *the* live
    vector for a loopback service. Binding 127.0.0.1 stops other machines
    connecting; it does not stop a page the operator visits from re-resolving
    its own hostname to 127.0.0.1 and becoming same-origin with this API — at
    which point it can import an arbitrary path, read the waveform back, and
    ``POST /api/renders`` for minutes of CPU and a ~300 MB file per request,
    with no rate limit and no delete path. Rebinding needs DNS, so such a
    request always carries the attacker's *hostname* in ``Host``; that header
    is the one thing distinguishing it from a genuine local request.

    Written here rather than using Starlette's ``TrustedHostMiddleware``, which
    would otherwise be the obvious choice, because that one extracts the host
    as ``header.split(":")[0]``. For ``[::1]:8765`` that yields ``"["`` and for
    a bare ``::1`` it yields ``""`` — so an IPv6 literal cannot be allow-listed
    there in any spelling, and ``sleepmix ui --host ::1`` (supported, tested,
    and opening ``http://[::1]:8765/`` in the browser) would 400 on every
    request from the operator's own machine. Do not "simplify" this back.

    Matching is exact against the lowercased host, plus ``"*"`` to allow any —
    which is what a wildcard bind gets, since it cannot enumerate the hostnames
    it is reachable by. A missing or unparseable ``Host`` is rejected.
    """

    def __init__(self, app, allowed_hosts) -> None:
        self.app = app
        self.allowed = {h.strip().lower().strip("[]") for h in allowed_hosts}
        self.allow_any = "*" in self.allowed

    async def __call__(self, scope, receive, send) -> None:
        if self.allow_any or scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        raw = ""
        for name, value in scope.get("headers") or []:
            if name.lower() == b"host":
                raw = value.decode("latin-1")
                break
        if _host_without_port(raw) in self.allowed:
            await self.app(scope, receive, send)
            return
        response = PlainTextResponse("Invalid host header", status_code=400)
        await response(scope, receive, send)


def create_app(store: Store | None = None,
               allowed_hosts: list[str] | None = None) -> FastAPI:
    static_dir = Path(__file__).resolve().parent.parent / "static"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Close only what this lifespan opened. An injected store belongs to
        # the caller: closing it on shutdown would leave a caller-held Store
        # with a dead connection, and a second TestClient context over the same
        # app would rebind that closed connection and raise ProgrammingError.
        owned = store is None
        app.state.store = Store() if owned else store
        orphaned = app.state.store.reconcile_orphaned_separations()
        if orphaned:
            print(f"sleepmix: reset {orphaned} separation(s) left running by a "
                  f"previous run")
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
            # wait=True, because `store.close()` is two lines below: with
            # wait=False the call returns immediately and a queued job that
            # starts draining afterwards hits a closed connection and prints a
            # traceback at shutdown. Safe to wait because `shutdown` cancels
            # every token first, so a running job stops at its next
            # `cancel.check()` rather than finishing a twenty-minute render.
            app.state.jobs.shutdown(wait=True)
            app.state.sessions.clear()
            if owned:
                app.state.store.close()

    app = FastAPI(title="sleepmix", version=sleepmix.__version__, lifespan=lifespan)

    # Rejected before any route runs — see _HostAllowList for why this exists
    # and why it is not TrustedHostMiddleware.
    app.add_middleware(
        _HostAllowList,
        allowed_hosts=list(allowed_hosts or DEFAULT_ALLOWED_HOSTS))

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": sleepmix.__version__, "warm": is_warm()}

    app.include_router(schema.router)
    app.include_router(config_api.router)
    app.include_router(songs.router)
    app.include_router(jobs_api.router)
    app.include_router(preview.router)
    app.include_router(renders.router)
    app.include_router(presets.router)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
