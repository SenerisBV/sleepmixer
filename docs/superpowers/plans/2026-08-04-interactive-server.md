# sleepmix Interactive Server Implementation Plan (Plan 2b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the local API — background jobs with live progress and cancellation, a session registry, instant decay-window previews, renders, and presets — so the Elm frontend has everything it needs.

**Architecture:** A single-worker job manager runs long work on a background thread, pushing structured progress into per-job subscriber queues that an SSE endpoint drains. A small LRU registry keeps `RenderSession` objects warm so a preview costs ~100 ms rather than re-running the phase vocoder. The server still holds no DSP knowledge — every endpoint decodes, calls into `sleepmix.*`, and encodes.

**Tech Stack:** Python ≥3.10, FastAPI, uvicorn, stdlib `sqlite3`, `concurrent.futures`, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-03-sleepmix-ui-design.md`
**Preceded by:** Plan 1 (`2026-08-03-core-hooks.md`) and Plan 2a (`2026-08-03-server-foundation.md`), both complete and merged.

## Global Constraints

- Python ≥3.10 (`requires-python` in `pyproject.toml`). No 3.11+ syntax.
- **`fastapi`, `uvicorn` and `starlette` may be imported only inside `sleepmix/server/`** — never from `sleepmix/*.py`. A subprocess test enforces this.
- Optional dependencies (`librosa`, `demucs`, `torch`, `pedalboard`, `pyrubberband`) must never be imported at module scope anywhere.
- **No new runtime dependencies.** Jobs use stdlib `concurrent.futures` and `threading`; SSE is plain `StreamingResponse`.
- Audio is always float32, shape `(n_frames, n_channels)`.
- **The server holds no business logic.** Anything that computes audio belongs in `sleepmix/*.py`.
- All persistent state lives under `paths.data_dir()`. Nothing may write to the current working directory.
- **Tests must never touch the operator's real data directory.** `tests/conftest.py`'s autouse fixture points `SLEEPMIX_DATA_DIR` at a tmpdir; anything reaching the filesystem must route through `paths.py`.
- **Tests must never invoke real Demucs.** `tests/conftest.py` provides a `stub_separation` fixture returning `fake_separate`; `RenderSession` takes an explicit `separate_fn`. A real call costs ~10 s.
- **`Store` is accessed from multiple threads.** Sync FastAPI routes already run in a threadpool, and this plan adds a genuine worker thread. Every `Store` method holds an `RLock`; do not remove it or add unlocked accessors.
- Existing style: module docstring explaining *why*, `from __future__ import annotations`, private helpers prefixed `_`.
- The CLI must keep working unchanged.

## File Structure

| File | Responsibility |
|---|---|
| `sleepmix/server/jobs.py` | Background job lifecycle, progress fan-out, cancellation |
| `sleepmix/server/sessions.py` | LRU registry of warm `RenderSession` objects |
| `sleepmix/server/api/jobs.py` | `/api/jobs/*` including the SSE stream |
| `sleepmix/server/api/preview.py` | `/api/preview` |
| `sleepmix/server/api/renders.py` | `/api/renders*` |
| `sleepmix/server/api/presets.py` | `/api/presets*` |
| `sleepmix/server/api/songs.py` | gains `POST /{song_id}/separate` |
| `sleepmix/audio.py` | gains `encode_wav` |
| `sleepmix/separation.py` | gains `invalidate_cache` |
| `sleepmix/config.py` | gains seed validation in `MixConfig.from_dict` |

---

### Task 1: `jobs.py` — background work with progress and cancellation

**Files:**
- Create: `sleepmix/server/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `ProgressReporter`, `ProgressEvent`, `CancelToken`, `Cancelled` from `sleepmix.progress`
- Produces:
  - `Job` dataclass: `id, kind, status, fraction, message, error, result, song_id`
  - `JobManager(loop=None, max_workers=1)` with:
    - `.submit(kind: str, fn: Callable[[ProgressReporter, CancelToken], dict], song_id: str | None = None) -> Job`
    - `.get(job_id: str) -> Job | None`
    - `.list() -> list[Job]`
    - `.cancel(job_id: str) -> bool`
    - `.subscribe(job_id: str) -> asyncio.Queue | None`
    - `.unsubscribe(job_id: str, queue) -> None`
    - `.shutdown(wait: bool = False) -> None`
  - `JOB_STATUSES = ("queued", "running", "done", "cancelled", "failed")`

**Why one worker:** renders are CPU-bound numpy over hundreds of loop iterations. Two concurrent renders would halve each other's speed and double peak memory, on a tool one person uses at a time. Serial is the honest default.

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
import asyncio
import threading
import time

import pytest

from sleepmix.server.jobs import JOB_STATUSES, JobManager


@pytest.fixture
def manager():
    m = JobManager()
    yield m
    m.shutdown(wait=True)


def _wait_for(manager, job_id, statuses, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.status in statuses:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job stayed {manager.get(job_id).status}")


def _wait_for_fraction(manager, job_id, fraction, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.fraction == fraction:
            return job
        time.sleep(0.01)
    raise AssertionError(f"fraction stayed {manager.get(job_id).fraction}")


def test_a_submitted_job_runs_and_reports_its_result(manager):
    release = threading.Event()

    def work(reporter, cancel):
        release.wait(timeout=5.0)
        return {"answer": 42}

    job = manager.submit("test", work)
    # Re-read through the manager: the Job returned by submit is a snapshot and
    # a trivial job can finish before the caller's next bytecode.
    assert manager.get(job.id).status in ("queued", "running")
    release.set()

    done = _wait_for(manager, job.id, ("done",))
    assert done.result == {"answer": 42}
    assert done.fraction == 1.0
    assert done.error is None


def test_progress_events_update_the_job(manager):
    """Hold the job open at 0.5 so the reported value is observable.

    Without the gate this could only assert the final 1.0, which completion
    sets regardless of whether any progress event was ever delivered."""
    release = threading.Event()

    def work(reporter, cancel):
        reporter.emit("stage-a", "half way", 0.5)
        release.wait(timeout=5.0)
        return {}

    job = manager.submit("test", work)
    midway = _wait_for_fraction(manager, job.id, 0.5)
    assert midway.message == "half way"
    release.set()
    done = _wait_for(manager, job.id, ("done",))
    assert done.fraction == 1.0


def test_a_raising_job_is_failed_not_lost(manager):
    def work(reporter, cancel):
        raise ValueError("boom")

    job = manager.submit("test", work)
    failed = _wait_for(manager, job.id, ("failed",))
    assert "boom" in failed.error
    assert failed.result is None


def test_cancelling_stops_the_work(manager):
    started = []

    def work(reporter, cancel):
        started.append(1)
        for _ in range(2000):
            cancel.check()
            time.sleep(0.001)
        return {"finished": True}

    job = manager.submit("test", work)
    while not started:
        time.sleep(0.01)
    assert manager.cancel(job.id) is True
    cancelled = _wait_for(manager, job.id, ("cancelled",))
    assert cancelled.result is None


def test_cancelling_an_unknown_job_is_false(manager):
    assert manager.cancel("nope") is False


def test_jobs_run_one_at_a_time(manager):
    """Serial by design — two renders would halve each other's speed."""
    concurrent = []
    running = []

    def work(reporter, cancel):
        running.append(1)
        concurrent.append(len(running))
        time.sleep(0.05)
        running.pop()
        return {}

    ids = [manager.submit("test", work).id for _ in range(3)]
    for job_id in ids:
        _wait_for(manager, job_id, ("done",))
    assert max(concurrent) == 1


def test_every_status_is_declared():
    assert set(JOB_STATUSES) == {"queued", "running", "done", "cancelled", "failed"}


@pytest.mark.asyncio
async def test_subscribers_receive_progress_events():
    loop = asyncio.get_running_loop()
    manager = JobManager(loop=loop)
    try:
        release = threading.Event()

        def work(reporter, cancel):
            # Held until the test has subscribed, so the event below cannot
            # fire before there is anyone listening for it.
            release.wait(timeout=5.0)
            reporter.emit("stage-a", "working", 0.5)
            return {}

        job = manager.submit("test", work)
        queue = manager.subscribe(job.id)
        assert queue is not None
        release.set()

        seen = []
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            seen.append(event)
            if event["status"] in ("done", "failed", "cancelled"):
                break
        assert any(e["message"] == "working" for e in seen)
        assert seen[-1]["status"] == "done"
    finally:
        release.set()   # or a failed assertion leaves the worker blocked
        manager.shutdown(wait=True)


@pytest.mark.asyncio
async def test_subscribing_to_a_finished_job_yields_its_final_state():
    """A client that connects late must not hang waiting for an event that
    already happened."""
    loop = asyncio.get_running_loop()
    manager = JobManager(loop=loop)
    try:
        job = manager.submit("test", lambda reporter, cancel: {"ok": True})
        deadline = time.time() + 5.0
        while manager.get(job.id).status != "done" and time.time() < deadline:
            time.sleep(0.01)
        queue = manager.subscribe(job.id)
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["status"] == "done"
    finally:
        manager.shutdown(wait=True)
```

- [ ] **Step 2: Add the asyncio test plugin**

The two `@pytest.mark.asyncio` tests need `pytest-asyncio`. In `pyproject.toml`, extend the `dev` extra:

```toml
dev = ["pytest>=7.4", "pytest-asyncio>=0.23", "fastapi>=0.110", "uvicorn>=0.27", "httpx>=0.27"]
```

Add to `Pipfile` under `[dev-packages]`:

```toml
pytest-asyncio = ">=0.23"
```

And configure the default loop scope so the marker works without per-test boilerplate — append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "strict"
```

Run: `pipenv install --dev`

- [ ] **Step 3: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server.jobs'`

- [ ] **Step 4: Write the implementation**

Create `sleepmix/server/jobs.py`:

```python
"""Background work with live progress and cooperative cancellation.

Separating a song takes ~10 seconds and rendering a mix takes minutes. Neither
can happen inside a request, so both run on a worker thread and the client
watches through :mod:`sleepmix.server.api.jobs`.

One worker, deliberately. Renders are CPU-bound numpy over hundreds of loop
iterations; two at once would halve each other's speed and double peak memory,
on a tool one person uses at a time.

The manager knows nothing about audio. A job is any callable taking a
``ProgressReporter`` and a ``CancelToken`` and returning a JSON-ready dict.
"""
from __future__ import annotations

import asyncio
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ..progress import Cancelled, CancelToken, ProgressEvent, ProgressReporter

JOB_STATUSES = ("queued", "running", "done", "cancelled", "failed")

JobFn = Callable[[ProgressReporter, CancelToken], dict]


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    fraction: float = 0.0
    message: str = ""
    error: str | None = None
    result: dict | None = None
    song_id: str | None = None

    def as_event(self) -> dict:
        return asdict(self)


class JobManager:
    """Runs jobs on a worker thread and fans progress out to subscribers."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None,
                 max_workers: int = 1) -> None:
        self._loop = loop
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="sleepmix-job")
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    # -- lifecycle ------------------------------------------------------
    def submit(self, kind: str, fn: JobFn, song_id: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, song_id=song_id)
        token = CancelToken()
        with self._lock:
            self._jobs[job.id] = job
            self._tokens[job.id] = token
            self._subscribers.setdefault(job.id, [])
        self._pool.submit(self._run, job.id, fn, token)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(job_id)
            job = self._jobs.get(job_id)
        if token is None or job is None or job.status in ("done", "failed", "cancelled"):
            return False
        token.cancel()
        return True

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            for token in self._tokens.values():
                token.cancel()
        self._pool.shutdown(wait=wait)

    # -- subscriptions --------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue | None:
        """Get a queue of progress events for ``job_id``.

        A job that has already finished pushes its final state immediately, so
        a client connecting late sees an outcome instead of hanging."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            queue: asyncio.Queue = asyncio.Queue()
            self._subscribers.setdefault(job_id, []).append(queue)
            terminal = job.status in ("done", "failed", "cancelled")
            snapshot = job.as_event()
        if terminal:
            queue.put_nowait(snapshot)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self._subscribers.get(job_id, [])
            if queue in queues:
                queues.remove(queue)

    # -- internals ------------------------------------------------------
    def _run(self, job_id: str, fn: JobFn, token: CancelToken) -> None:
        self._update(job_id, status="running")
        reporter = ProgressReporter(lambda event: self._on_event(job_id, event))
        try:
            result = fn(reporter, token)
        except Cancelled:
            self._update(job_id, status="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
            self._update(job_id, status="failed",
                         error=f"{type(exc).__name__}: {exc}",
                         message="Failed")
            traceback.print_exc()
        else:
            self._update(job_id, status="done", fraction=1.0,
                         result=result, message="Done")

    def _on_event(self, job_id: str, event: ProgressEvent) -> None:
        self._update(job_id, fraction=event.fraction, message=event.message)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            snapshot = job.as_event()
            queues = list(self._subscribers.get(job_id, []))
        for queue in queues:
            self._publish(queue, snapshot)

    def _publish(self, queue: asyncio.Queue, snapshot: dict) -> None:
        """Hand a snapshot to a queue owned by the event loop.

        ``_update`` runs on the worker thread, so the put must be marshalled
        across; ``call_soon_threadsafe`` is the only safe way to touch an
        asyncio primitive from another thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, snapshot)
        except RuntimeError:
            pass  # loop shut down between the check and the call
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_jobs.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml Pipfile Pipfile.lock sleepmix/server/jobs.py tests/test_jobs.py
git commit -m "feat: background job manager with progress fan-out and cancellation"
```

---

### Task 2: `sessions.py` — keep sessions warm

**Files:**
- Create: `sleepmix/server/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `RenderSession(input_path, config, separate_fn=None)` from `sleepmix.session`
- Produces:
  - `SessionRegistry(max_sessions: int = 2, separate_fn=None)` with:
    - `.get(song_id: str, input_path: str, config: MixConfig) -> RenderSession`
    - `.discard(song_id: str) -> None`
    - `.clear() -> None`
    - `.song_ids() -> list[str]` — most-recently-used last

**Why a cap:** a session holds every separated stem decoded in memory. A five-minute stereo track at 44.1 kHz is ~50 MB per stem, so four stems plus the stretched loops is a few hundred megabytes per song. Two is enough to A/B without the process ballooning.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sessions.py`:

```python
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig
from sleepmix.server.sessions import SessionRegistry


def _song(path, sr=22050, secs=3.0):
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return str(path)


@pytest.fixture
def registry(stub_separation):
    return SessionRegistry(max_sessions=2, separate_fn=stub_separation)


def test_the_same_song_returns_the_same_session(tmp_path, registry):
    path = _song(tmp_path / "a.wav")
    first = registry.get("song-a", path, MixConfig())
    second = registry.get("song-a", path, MixConfig())
    assert first is second


def test_a_config_change_updates_rather_than_rebuilds(tmp_path, registry):
    """Rebuilding would re-run separation — the whole point is to avoid that."""
    path = _song(tmp_path / "a.wav")
    session = registry.get("song-a", path, MixConfig())
    stems = session.stems()

    faster = MixConfig()
    faster.tempo.speed = 0.5
    again = registry.get("song-a", path, faster)

    assert again is session
    assert again.stems() is stems
    assert again.config.tempo.speed == 0.5


def test_least_recently_used_is_evicted(tmp_path, registry):
    a = registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.get("c", _song(tmp_path / "c.wav"), MixConfig())

    assert registry.song_ids() == ["b", "c"]
    assert registry.get("a", _song(tmp_path / "a.wav"), MixConfig()) is not a


def test_touching_a_session_makes_it_most_recent(tmp_path, registry):
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())   # touch a
    registry.get("c", _song(tmp_path / "c.wav"), MixConfig())   # evicts b

    assert registry.song_ids() == ["a", "c"]


def test_discard_and_clear(tmp_path, registry):
    registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    registry.discard("a")
    assert registry.song_ids() == []
    registry.discard("a")  # discarding twice must not raise
    registry.get("b", _song(tmp_path / "b.wav"), MixConfig())
    registry.clear()
    assert registry.song_ids() == []


def test_a_changed_source_path_rebuilds(tmp_path, registry):
    """Re-importing a moved file under the same id must not serve stale audio."""
    first = registry.get("a", _song(tmp_path / "a.wav"), MixConfig())
    second = registry.get("a", _song(tmp_path / "moved.wav"), MixConfig())
    assert second is not first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server.sessions'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/server/sessions.py`:

```python
"""Keep a few songs open so previews stay interactive.

A ``RenderSession`` memoizes separation, loop detection and time-stretching.
Building one costs seconds; reusing one makes a preview cost milliseconds. The
registry exists so consecutive requests about the same song hit the same warm
session instead of paying that cost again.

It is capped because a session holds every stem decoded in memory — a
five-minute stereo track is roughly fifty megabytes per stem, so a few hundred
per song once the stretched loops are cached. Two is enough to A/B two songs
without the process ballooning.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from ..config import MixConfig
from ..session import RenderSession


class SessionRegistry:
    def __init__(self, max_sessions: int = 2, separate_fn=None) -> None:
        self.max_sessions = max(int(max_sessions), 1)
        self._separate_fn = separate_fn
        self._lock = threading.RLock()
        # song_id -> (input_path, session); ordered least-recently-used first.
        self._sessions: OrderedDict[str, tuple[str, RenderSession]] = OrderedDict()

    def get(self, song_id: str, input_path: str, config: MixConfig) -> RenderSession:
        """The warm session for ``song_id``, building one only if needed."""
        with self._lock:
            existing = self._sessions.get(song_id)
            if existing is not None and existing[0] == input_path:
                session = existing[1]
                # update_config invalidates only the stages the change affects,
                # so a tempo tweak keeps the separated stems.
                session.update_config(config)
                self._sessions.move_to_end(song_id)
                return session

            session = RenderSession(input_path, config, separate_fn=self._separate_fn)
            self._sessions[song_id] = (input_path, session)
            self._sessions.move_to_end(song_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return session

    def discard(self, song_id: str) -> None:
        with self._lock:
            self._sessions.pop(song_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def song_ids(self) -> list[str]:
        """Live song ids, least-recently-used first."""
        with self._lock:
            return list(self._sessions.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_sessions.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sleepmix/server/sessions.py tests/test_sessions.py
git commit -m "feat: LRU registry of warm render sessions"
```

---

### Task 3: Cache invalidation and `POST /api/songs/{id}/separate`

**Files:**
- Modify: `sleepmix/separation.py` (add `invalidate_cache`)
- Modify: `sleepmix/server/api/songs.py`
- Modify: `sleepmix/server/app.py` (own a `JobManager` and a `SessionRegistry` on `app.state`)
- Test: `tests/test_separation.py`, `tests/test_api_separate.py` (new)

**Interfaces:**
- Consumes: `JobManager` (Task 1), `SessionRegistry` (Task 2), `separate_detailed` / `SeparationResult`
- Produces:
  - `separation.invalidate_cache(input_path, model="htdemucs_ft", cache_dir=...) -> bool`
  - `POST /api/songs/{song_id}/separate?force=false` → `202` with the job dict
  - `app.state.jobs: JobManager`, `app.state.sessions: SessionRegistry`

**Why invalidation is required, not optional.** `_cache_key` is `(abspath, size, mtime, model)` and does not include whether Demucs was available. Once a fallback is cached, every later `separate_detailed` short-circuits and returns it — *including after the user installs the `separation` extra*. Without a force path, the endpoint would report "Demucs unavailable" forever on a machine where Demucs now works.

- [ ] **Step 1: Write the failing tests for invalidation**

Add to `tests/test_separation.py`:

```python
def test_invalidate_cache_forces_a_recompute(tmp_path, monkeypatch):
    """Without this, a cached fallback is permanent — the cache key does not
    include whether Demucs was available, so installing it later changes
    nothing."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    calls = []

    def failing(input_path, model):
        calls.append(1)
        raise RuntimeError("no torch")

    monkeypatch.setattr(sep, "_demucs_separate", failing)
    separate_detailed(str(song), cache_dir=cache)
    separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 1

    assert sep.invalidate_cache(str(song), cache_dir=cache) is True
    separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 2


def test_invalidate_cache_is_false_when_nothing_was_cached(tmp_path):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    assert sep.invalidate_cache(str(song), cache_dir=str(tmp_path / "cache")) is False


def test_a_successful_rerun_clears_the_stale_marker(tmp_path, monkeypatch):
    """The whole point of invalidation: a fallback must stop being reported
    once the real thing works."""
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    assert separate_detailed(str(song), cache_dir=cache).fallback_reason is not None

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)
    sep.invalidate_cache(str(song), cache_dir=cache)
    result = separate_detailed(str(song), cache_dir=cache)
    assert result.fallback_reason is None
    assert set(result.stems) == {"vocals", "drums", "bass", "other"}
```

`tests/test_separation.py` already imports `AudioBuffer`; if not, add `from sleepmix.audio import AudioBuffer` to the imports.

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_separation.py -v`
Expected: FAIL — `AttributeError: module 'sleepmix.separation' has no attribute 'invalidate_cache'`

- [ ] **Step 3: Implement invalidation**

Add to `sleepmix/separation.py`, next to the other cache helpers:

```python
def invalidate_cache(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> bool:
    """Delete the cached separation for ``input_path``. True if there was one.

    The cache key is ``(path, size, mtime, model)`` and deliberately says
    nothing about whether Demucs was importable at the time. That is fine for
    a successful separation and wrong for a fallback: without this, a track
    separated before the ``separation`` extra was installed would report itself
    as a fallback forever."""
    import shutil

    directory = _cache_path(cache_dir, _cache_key(input_path, model))
    if not os.path.isdir(directory):
        return False
    shutil.rmtree(directory)
    return True
```

- [ ] **Step 4: Run to verify the invalidation tests pass**

Run: `pipenv run pytest tests/test_separation.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Write the failing endpoint test**

Create `tests/test_api_separate.py`:

```python
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, name="a.wav", sr=22050, secs=2.0):
    path = tmp_path / name
    t = np.arange(int(sr * secs)) / sr
    y = (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def _await_job(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_separate_records_status_and_stems(client, tmp_path, monkeypatch):
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)
    song = _import_song(client, tmp_path)

    r = client.post(f"/api/songs/{song['id']}/separate")
    assert r.status_code == 202
    _await_job(client, r.json()["id"])

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "done"
    assert updated["separation_reason"] is None
    assert set(updated["stems"]) == {"vocals", "drums", "bass", "other"}


def test_separate_records_the_fallback_reason(client, tmp_path, monkeypatch):
    """This is the whole point: a UI must be able to say why there is one stem."""
    import sleepmix.separation as sep

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    song = _import_song(client, tmp_path)

    job = client.post(f"/api/songs/{song['id']}/separate").json()
    _await_job(client, job["id"])

    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "fallback"
    assert "no torch" in updated["separation_reason"]
    assert updated["stems"] == ["mix"]


def test_separate_404s_for_an_unknown_song(client):
    assert client.post("/api/songs/nope/separate").status_code == 404


def test_separate_404s_when_the_file_has_moved(client, tmp_path):
    import os

    song = _import_song(client, tmp_path)
    os.remove(song["path"])
    r = client.post(f"/api/songs/{song['id']}/separate")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()


def test_force_reseparates_after_a_fallback(client, tmp_path, monkeypatch):
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    song = _import_song(client, tmp_path)
    _await_job(client, client.post(f"/api/songs/{song['id']}/separate").json()["id"])
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "fallback"

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)

    # Without force the cached fallback wins, which is exactly the bug.
    _await_job(client, client.post(f"/api/songs/{song['id']}/separate").json()["id"])
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "fallback"

    _await_job(client, client.post(
        f"/api/songs/{song['id']}/separate?force=true").json()["id"])
    updated = client.get(f"/api/songs/{song['id']}").json()
    assert updated["separation_status"] == "done"
    assert updated["separation_reason"] is None
```

- [ ] **Step 6: Own the job manager and session registry on the app**

In `sleepmix/server/app.py`, add to the imports:

```python
from .jobs import JobManager
from .sessions import SessionRegistry
```

Inside the `lifespan` handler, after the store is created, add:

```python
        # The manager needs the running loop so it can marshal progress events
        # from the worker thread into subscriber queues.
        app.state.jobs = JobManager(loop=asyncio.get_running_loop())
        app.state.sessions = SessionRegistry()
```

and in the `finally` block, before the store is closed:

```python
            app.state.jobs.shutdown()
            app.state.sessions.clear()
```

Then mount the new router (added in the next step):

```python
    app.include_router(jobs_api.router)
```

with `from .api import jobs as jobs_api` alongside the existing router imports. The `/api/jobs/{id}` route it provides is what the tests above poll.

- [ ] **Step 7: Add the jobs read API**

Create `sleepmix/server/api/jobs.py` with the polling routes only — the SSE stream arrives in Task 4:

```python
"""``/api/jobs`` — watch and cancel background work.

Polling and streaming both live here. The stream is the one the UI uses; the
polling route exists because it is far easier to test and to reach for from a
shell.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(request: Request) -> dict:
    return {"jobs": [job.as_event() for job in request.app.state.jobs.list()]}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return job.as_event()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    if request.app.state.jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="No such job")
    cancelled = request.app.state.jobs.cancel(job_id)
    return {"cancelled": cancelled, "job": request.app.state.jobs.get(job_id).as_event()}
```

- [ ] **Step 8: Add the separate endpoint**

Add to `sleepmix/server/api/songs.py`:

```python
from ...paths import cache_dir
from ...separation import invalidate_cache, separate_detailed


@router.post("/{song_id}/separate", status_code=202)
def separate_song(song_id: str, request: Request, force: bool = False) -> dict:
    """Kick off stem separation as a background job.

    ``force`` deletes the cached result first. That matters because the cache
    key says nothing about whether Demucs was importable: without it, a song
    separated before the ``separation`` extra was installed would keep
    reporting itself as a fallback."""
    store = request.app.state.store
    song = store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    path = song["path"]
    model = request.app.state.separation_model
    sessions = request.app.state.sessions

    def work(reporter, cancel) -> dict:
        reporter.emit("separate", "Separating stems…", 0.0)
        if force:
            invalidate_cache(path, model, cache_dir=str(cache_dir()))
        cancel.check()
        result = separate_detailed(path, model, cache_dir=str(cache_dir()))
        status = "fallback" if result.fallback_reason else "done"
        store.update_song(song_id,
                          separation_status=status,
                          separation_reason=result.fallback_reason,
                          stems=sorted(result.stems))
        # The song's audio changed shape underneath any warm session.
        sessions.discard(song_id)
        reporter.emit("separate", "Done", 1.0)
        return {"status": status, "stems": sorted(result.stems)}

    store.update_song(song_id, separation_status="running", separation_reason=None)
    job = request.app.state.jobs.submit("separate", work, song_id=song_id)
    return job.as_event()
```

Add `app.state.separation_model = MixConfig().separation_model` in the lifespan handler in `sleepmix/server/app.py`, with `from ..config import MixConfig` imported there. Keeping the model on app state rather than reaching for a default inside the request keeps the endpoint honest about where configuration comes from.

- [ ] **Step 9: Run the tests**

Run: `pipenv run pytest tests/test_api_separate.py tests/test_separation.py -v`
Expected: PASS

- [ ] **Step 10: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add sleepmix/separation.py sleepmix/server tests/test_separation.py tests/test_api_separate.py
git commit -m "feat: separation as a background job, with cache invalidation"
```

---

### Task 4: `GET /api/jobs/{id}/events` — the SSE stream

**Files:**
- Modify: `sleepmix/server/api/jobs.py`
- Test: `tests/test_api_jobs_sse.py` (new)

**Interfaces:**
- Consumes: `JobManager.subscribe` / `.unsubscribe` (Task 1)
- Produces: `GET /api/jobs/{job_id}/events` — `text/event-stream`, one `data:` line per event, closing after a terminal status

**Why SSE and not WebSockets:** progress is one-directional and SSE reconnects on its own. The Elm side cannot open an `EventSource` (no `elm/http` support), so a small JS port owns the connection and forwards parsed events inward — which is another reason to keep the payload plain JSON objects rather than a bespoke framing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_jobs_sse.py`:

```python
import json
import time

import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _events(raw: str) -> list[dict]:
    return [json.loads(line[len("data: "):])
            for line in raw.splitlines() if line.startswith("data: ")]


def test_stream_delivers_events_and_closes_on_completion(client):
    def work(reporter, cancel):
        reporter.emit("stage", "working", 0.5)
        return {"ok": True}

    job = client.app.state.jobs.submit("test", work)
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = "".join(response.iter_text())

    events = _events(body)
    assert events, "stream produced no events"
    assert events[-1]["status"] == "done"


def test_stream_for_a_finished_job_returns_its_final_state(client):
    """A client that connects after the job finished must not hang."""
    job = client.app.state.jobs.submit("test", lambda reporter, cancel: {"ok": True})
    deadline = time.time() + 5.0
    while client.app.state.jobs.get(job.id).status != "done" and time.time() < deadline:
        time.sleep(0.01)

    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        body = "".join(response.iter_text())
    events = _events(body)
    assert events[-1]["status"] == "done"


def test_stream_404s_for_an_unknown_job(client):
    assert client.get("/api/jobs/nope/events").status_code == 404


def test_a_failed_job_closes_the_stream_with_its_error(client):
    def work(reporter, cancel):
        raise ValueError("boom")

    job = client.app.state.jobs.submit("test", work)
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        body = "".join(response.iter_text())
    events = _events(body)
    assert events[-1]["status"] == "failed"
    assert "boom" in events[-1]["error"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_api_jobs_sse.py -v`
Expected: FAIL — 404, because the route does not exist yet.

- [ ] **Step 3: Add the stream endpoint**

Add to `sleepmix/server/api/jobs.py`:

```python
import asyncio
import json

from fastapi.responses import StreamingResponse

_TERMINAL = ("done", "failed", "cancelled")
_HEARTBEAT_SECONDS = 15.0


@router.get("/{job_id}/events")
async def stream_job(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events for one job, closing once it reaches a terminal state.

    SSE rather than WebSockets because progress only travels one way and SSE
    reconnects by itself. Elm cannot open an EventSource, so a small JS port
    owns the connection and forwards parsed events in — which is why the
    payload stays a plain JSON object rather than a bespoke framing."""
    manager = request.app.state.jobs
    queue = manager.subscribe(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No such job")

    async def events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(),
                                                   timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Comment frame: keeps proxies and browsers from timing out
                    # a long render that has not emitted lately.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event["status"] in _TERMINAL:
                    return
        finally:
            manager.unsubscribe(job_id, queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

- [ ] **Step 4: Run the tests**

Run: `pipenv run pytest tests/test_api_jobs_sse.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sleepmix/server/api/jobs.py tests/test_api_jobs_sse.py
git commit -m "feat: SSE progress stream for background jobs"
```

---

### Task 5: `encode_wav` and `POST /api/preview`

**Files:**
- Modify: `sleepmix/audio.py` (add `encode_wav`)
- Modify: `sleepmix/config.py` (validate `seed` in `from_dict`)
- Modify: `sleepmix/session.py` (add the `master_gain` memo slot)
- Modify: `sleepmix/preview.py` (add `master_gain`, and a `master` parameter)
- Modify: `tests/test_preview.py` (the bit-identity test opts out of mastering)
- Create: `sleepmix/server/api/preview.py`
- Modify: `sleepmix/server/app.py` (mount the router)
- Test: `tests/test_audio_encode.py` (new), `tests/test_api_preview.py` (new)

**Interfaces:**
- Consumes: `render_window`, `SessionRegistry.get`, `db_to_amp`
- Produces:
  - `audio.encode_wav(buf: AudioBuffer, subtype: str = "PCM_16") -> bytes`
  - `preview.master_gain(session) -> float`
  - `render_window(session, progress, stems=None, reverb=True, master=True)` — **signature change**, new trailing parameter
  - `RenderSession.master_gain: float | None` — memo slot, cleared by `update_config`
  - `POST /api/preview` body `{song_id, progress, stems?, reverb?, config?}` → `audio/wav`

**This is the payoff endpoint.** `apply_decay` is a pure function of progress, so rendering the point two-thirds through a twenty-five-minute mix costs one loop iteration — measured at tens of milliseconds per stem — rather than rendering everything before it. The session registry is what keeps that true across requests.

**Seed validation belongs here** because this is the first place a config crosses an API boundary. `util.iteration_rng` feeds `seed` to numpy's `SeedSequence`, which requires non-negative entropy; a negative seed from a UI field would raise deep in the DSP with an unhelpful message.

### Master-gain matching — found by listening, not by testing

A preview is one window of a stream that `run_pipeline` peak-normalizes **as a
whole**. The mix's peak sits early, where the audio is least eroded, so the
finished render is scaled down by a single global factor — measured at 0.656,
or −3.7 dB, on a default config. A preview gets no such scaling, so it plays
about 4 dB hot against the render it claims to represent.

This was caught by ear and confirmed by measurement. Sliding a preview-length
window across a real render and comparing on spectral centroid (which tracks
the lowpass sweep, and is level-invariant) put the best match within 30 s of the
predicted position — the *content* was right. Comparing on RMS put the best
match at the very start of the mix. The operator, reading both cues at once,
placed the preview at roughly half its true position in the arc.

None of the 118 tests could have caught it: the bit-identity test compares
pre-reverb and pre-master, so it passed throughout while the audible result
diverged. Loudness reads as less-decayed, which corrupts exactly the judgement
a preview exists to support.

**The fix, and why it is cheap.** Window peak falls monotonically across the arc
— decay only removes energy — so the first iteration is the loudest and a single
window predicts the factor the master will apply. Measured across a real song:

| progress | window peak |
|---|---|
| 0.00 | 1.358 |
| 0.50 | 1.049 |
| 1.00 | 0.753 |

`target / 1.358 = 0.656`, matching the render's actual factor.

**What this must not become.** Normalizing each preview to its own peak would
make every point in the arc equally loud and destroy the decay entirely. One
factor, computed once, applied to all windows — the arc is preserved because
later windows are genuinely quieter.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio_encode.py`:

```python
import io

import numpy as np
import soundfile as sf

from sleepmix.audio import AudioBuffer, encode_wav


def _buf(secs=0.5, sr=22050):
    t = np.arange(int(sr * secs)) / sr
    y = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def test_encodes_a_riff_wav():
    data = encode_wav(_buf())
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_round_trips_through_soundfile():
    buf = _buf()
    back, sr = sf.read(io.BytesIO(encode_wav(buf)), dtype="float32", always_2d=True)
    assert sr == buf.sr
    assert back.shape == buf.data.shape
    assert np.abs(back - buf.data).max() < 1e-3   # PCM_16 quantization


def test_encodes_an_empty_buffer_without_raising():
    data = encode_wav(AudioBuffer(np.zeros((0, 2), dtype=np.float32), 44100))
    assert data[:4] == b"RIFF"
```

Add to `tests/test_config.py`:

```python
def test_from_dict_rejects_a_negative_seed():
    """numpy's SeedSequence requires non-negative entropy; a negative seed
    would raise deep inside the DSP with an unhelpful message."""
    import pytest

    with pytest.raises(ValueError, match="seed"):
        MixConfig.from_dict({"seed": -1})


def test_from_dict_accepts_zero_and_positive_seeds():
    assert MixConfig.from_dict({"seed": 0}).seed == 0
    assert MixConfig.from_dict({"seed": 7}).seed == 7
```

Create `tests/test_api_preview.py`:

```python
import io
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client(stub_separation):
    # stub_separation patches sleepmix.session.separate, which RenderSession
    # resolves at construction — so the registry picks up the stub without
    # anything being injected into it.
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, sr=22050, secs=3.0):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def test_preview_returns_playable_wav(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content), dtype="float32", always_2d=True)
    assert data.shape[0] > 0
    assert np.all(np.isfinite(data))


def test_preview_is_fast_once_the_session_is_warm(client, tmp_path):
    song = _import_song(client, tmp_path)
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.5})
    start = time.perf_counter()
    client.post("/api/preview", json={"song_id": song["id"], "progress": 0.6})
    assert time.perf_counter() - start < 3.0


def test_different_points_in_the_arc_sound_different(client, tmp_path):
    song = _import_song(client, tmp_path)
    early = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": 0.0}).content
    late = client.post("/api/preview",
                       json={"song_id": song["id"], "progress": 1.0}).content
    assert early != late


def test_soloing_a_stem_changes_the_result(client, tmp_path):
    song = _import_song(client, tmp_path)
    everything = client.post("/api/preview",
                             json={"song_id": song["id"], "progress": 0.5}).content
    one = client.post("/api/preview",
                      json={"song_id": song["id"], "progress": 0.5,
                            "stems": ["vocals"]}).content
    assert everything != one


def test_preview_honours_a_supplied_config(client, tmp_path):
    song = _import_song(client, tmp_path)
    default = client.post("/api/preview",
                          json={"song_id": song["id"], "progress": 0.5}).content
    slower = client.post("/api/preview",
                         json={"song_id": song["id"], "progress": 0.5,
                               "config": {"tempo": {"speed": 0.4}}}).content
    assert default != slower


def test_preview_rejects_a_negative_seed(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/preview",
                    json={"song_id": song["id"], "progress": 0.5,
                          "config": {"seed": -5}})
    assert r.status_code == 400
    assert "seed" in r.json()["detail"].lower()


def test_preview_rejects_out_of_range_progress(client, tmp_path):
    song = _import_song(client, tmp_path)
    for progress in (-1.0, 2.0):
        r = client.post("/api/preview",
                        json={"song_id": song["id"], "progress": progress})
        assert r.status_code == 422


def test_preview_404s_for_an_unknown_song(client):
    r = client.post("/api/preview", json={"song_id": "nope", "progress": 0.5})
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_audio_encode.py tests/test_api_preview.py -v`
Expected: FAIL — `ImportError: cannot import name 'encode_wav'`

- [ ] **Step 3: Add `encode_wav`**

Add to `sleepmix/audio.py`:

```python
def encode_wav(buf: AudioBuffer, subtype: str = "PCM_16") -> bytes:
    """Encode ``buf`` as a WAV file in memory.

    Previews are handed to the browser as bytes and never touch disk — writing
    a temp file per slider drag would be both slower and a cleanup problem.
    PCM_16 rather than PCM_24 because this is for listening, not archiving, and
    it halves what crosses the wire."""
    import io

    import soundfile as sf

    bio = io.BytesIO()
    sf.write(bio, buf.data, buf.sr, subtype=subtype, format="WAV")
    return bio.getvalue()
```

- [ ] **Step 4: Validate the seed**

In `sleepmix/config.py`, change `MixConfig.from_dict` to validate after building:

```python
    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "MixConfig":
        config = _build(cls, d or {})
        config.validate()
        return config

    def validate(self) -> None:
        """Raise ``ValueError`` for values that would fail deep in the DSP.

        ``seed`` feeds numpy's ``SeedSequence`` via ``util.iteration_rng``,
        which requires non-negative entropy. Caught here because this is where
        a config from a UI field first arrives."""
        if int(self.seed) < 0:
            raise ValueError(f"seed must be non-negative, got {self.seed}")
```

`MixConfig.from_yaml` already routes through `from_dict`, so it inherits the check.

- [ ] **Step 5: Add the memo slot to the session**

In `sleepmix/session.py`, add to `__init__`:

```python
        # Filled in by preview.master_gain. It lives here rather than in
        # preview.py because it is invalidated by exactly the config changes
        # this class already tracks — and preview imports session, so session
        # cannot import preview to own the computation itself.
        self.master_gain: float | None = None
```

and clear it at the top of `update_config`:

```python
        self.master_gain = None
```

- [ ] **Step 6: Add `master_gain` and the `master` parameter**

In `sleepmix/preview.py`, add the import `from .util import db_to_amp` if it is
not already present, then add above `render_window`:

```python
def master_gain(session: RenderSession) -> float:
    """The gain ``run_pipeline``'s mastering stage will apply to this mix.

    A preview is one window of a stream that gets peak-normalized as a whole.
    Without this correction a preview plays about 4 dB above the render it
    represents — and louder reads as *less decayed*, which corrupts exactly the
    judgement a preview exists to support. Found by listening; no test caught it,
    because the bit-identity check compares pre-reverb and pre-master.

    One window is enough: decay only removes energy, so the peak falls
    monotonically across the arc and the first iteration is the loudest."""
    if session.master_gain is None:
        loudest = render_window(session, 0.0, reverb=True, master=False)
        peak = float(np.abs(loudest.data).max())
        target = db_to_amp(session.config.output.peak_db)
        session.master_gain = float(target / peak) if peak > 1e-9 else 1.0
    return session.master_gain
```

Change `render_window`'s signature to take a trailing `master: bool = True`, and
apply the gain just before returning — after the stems are summed, so one factor
covers the whole window:

```python
    out = AudioBuffer(acc, sr)
    if master:
        # One factor for every window, never per-window normalization: the arc
        # survives only because later windows stay genuinely quieter.
        out = AudioBuffer(out.data * master_gain(session), sr)
    return out
```

Update the docstring to say the window is master-matched by default.

**Watch the recursion:** `master_gain` calls `render_window(..., master=False)`.
If you leave that argument off you get infinite recursion, and the tests will
hang rather than fail.

- [ ] **Step 7: Let the bit-identity test opt out**

`tests/test_preview.py::test_window_matches_decayed_iteration_pre_reverb`
compares a window against a raw `decayed_iteration` call. That comparison is
about the pre-reverb, pre-master signal path, so it must now pass
`master=False`:

```python
    out = render_window(s, progress, stems=[name], reverb=False, master=False)
```

Do not change anything else about that test — it is the one pinning
preview/render equality for content.

Check the other tests in that file: any that compare two windows against each
other are unaffected, because both sides get the same factor.

- [ ] **Step 8: Write the test that would have caught this**

Add to `tests/test_preview.py`:

```python
def test_a_mastered_preview_sits_at_the_render_s_level(tmp_path, stub_separation):
    """Preview loudness must track the render's, not float above it.

    This is the check that was missing. The bit-identity test compares
    pre-master, so it passed while previews played ~4 dB hot — and because
    louder reads as less decayed, tuning done in the UI was being done against
    something that would never ship."""
    from sleepmix.audio import load_audio
    from sleepmix.disintegration import plan_iterations
    from sleepmix.pipeline import run_pipeline

    song = tmp_path / "s.wav"
    _song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.5
    cfg.output.sample_rate = 22050      # match the source: no resample step
    cfg.output.fade_in_s = 0.0
    cfg.output.fade_out_s = 0.0
    cfg.reverb.wet = 0.0                # compare the dry path only

    out = tmp_path / "mix.wav"
    run_pipeline(str(song), cfg, str(out))
    rendered = load_audio(str(out))

    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    n_iter, xfade = plan_iterations(
        loop.n_frames, target_frames, cfg.output.cycle_crossfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)

    i = max(n_iter // 2, 1)
    progress = i / max(n_iter - 1, 1)
    lo, hi = i * stride + xfade, min((i + 1) * stride, target_frames)
    assert hi > lo, "test setup produced no clean region"

    window = render_window(session, progress, reverb=False)   # mastered
    rendered_rms = float(np.sqrt(np.mean(rendered.data[lo:hi] ** 2)))
    window_rms = float(np.sqrt(np.mean(window.data[xfade:xfade + (hi - lo)] ** 2)))

    assert rendered_rms > 0
    ratio = window_rms / rendered_rms
    assert 0.85 < ratio < 1.15, f"preview is {20 * np.log10(ratio):+.1f} dB off the render"


def test_master_gain_is_computed_once_per_config(tmp_path, stub_separation):
    """It costs a window render, so it must not run on every preview."""
    from sleepmix.preview import master_gain

    s = _session(tmp_path, stub_separation)
    first = master_gain(s)
    assert s.master_gain == first
    assert master_gain(s) is s.master_gain

    changed = MixConfig()
    changed.output.duration_min = 2.0
    changed.tempo.speed = 0.5
    s.update_config(changed)
    assert s.master_gain is None, "a config change must invalidate the gain"


def test_mastering_preserves_the_arc(tmp_path, stub_separation):
    """One factor for all windows — not per-window normalization.

    If each window were normalized to its own peak, every point in the decay
    arc would come back equally loud and the whole effect would be inaudible in
    preview."""
    s = _session(tmp_path, stub_separation)
    early = render_window(s, 0.0, reverb=False)
    late = render_window(s, 1.0, reverb=False)
    assert float(np.abs(late.data).max()) < float(np.abs(early.data).max())
```

- [ ] **Step 9: Add the preview router**

Create `sleepmix/server/api/preview.py`:

```python
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
```

- [ ] **Step 10: Mount it**

In `sleepmix/server/app.py`, add `preview` to the `from .api import ...` line and `app.include_router(preview.router)` alongside the others.

- [ ] **Step 11: Run the tests**

Run: `pipenv run pytest tests/test_audio_encode.py tests/test_api_preview.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 12: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add sleepmix/audio.py sleepmix/config.py sleepmix/server tests/test_audio_encode.py tests/test_api_preview.py tests/test_config.py
git commit -m "feat: instant decay-window previews over HTTP"
```

---

### Task 6: `/api/renders` — start, watch, download

**Files:**
- Create: `sleepmix/server/api/renders.py`
- Modify: `sleepmix/server/app.py` (mount)
- Test: `tests/test_api_renders.py` (new)

**Interfaces:**
- Consumes: `run_pipeline(input_path, config, output_path, progress=print, reporter=None, cancel=None)`, `JobManager`, `Store`
- Produces:
  - `POST /api/renders` body `{song_id, config?, preset_id?}` → `202` with `{job, render}`
  - `GET /api/renders` → `{"renders": [...]}`
  - `GET /api/renders/{render_id}` → render dict, 404 if absent
  - `GET /api/renders/{render_id}/audio` → the WAV file
  - Renders are written to `paths.data_dir()/renders/<render_id>.wav`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_renders.py`:

```python
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client(stub_separation):
    with TestClient(create_app()) as c:
        yield c


def _import_song(client, tmp_path, sr=22050, secs=3.0):
    path = tmp_path / "a.wav"
    t = np.arange(int(sr * secs)) / sr
    y = (sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return client.post("/api/songs", json={"path": str(path)}).json()


def _await_job(client, job_id, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("render never finished")


_SHORT = {"output": {"duration_min": 0.05, "sample_rate": 22050,
                     "fade_in_s": 0.0, "fade_out_s": 0.0}}


def test_render_produces_a_downloadable_file(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/renders", json={"song_id": song["id"], "config": _SHORT})
    assert r.status_code == 202
    body = r.json()
    job = _await_job(client, body["job"]["id"])
    assert job["status"] == "done", job.get("error")

    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["status"] == "done"

    audio = client.get(f"/api/renders/{body['render']['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_render_records_the_config_that_made_it(client, tmp_path):
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    _await_job(client, body["job"]["id"])
    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["config"]["output"]["duration_min"] == 0.05


def test_listing_renders(client, tmp_path):
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    _await_job(client, body["job"]["id"])
    ids = [r["id"] for r in client.get("/api/renders").json()["renders"]]
    assert body["render"]["id"] in ids


def test_render_404s_for_an_unknown_song(client):
    r = client.post("/api/renders", json={"song_id": "nope"})
    assert r.status_code == 404


def test_audio_404s_before_the_render_finishes(client, tmp_path):
    """The row exists from the moment the job is queued; the file does not."""
    song = _import_song(client, tmp_path)
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": _SHORT}).json()
    render_id = body["render"]["id"]
    early = client.get(f"/api/renders/{render_id}/audio")
    _await_job(client, body["job"]["id"])
    assert early.status_code in (404, 409)


def test_a_cancelled_render_is_marked_cancelled(client, tmp_path):
    song = _import_song(client, tmp_path)
    long_config = {"output": {"duration_min": 30.0, "sample_rate": 22050}}
    body = client.post("/api/renders",
                       json={"song_id": song["id"], "config": long_config}).json()
    job_id = body["job"]["id"]

    deadline = time.time() + 10.0
    while client.get(f"/api/jobs/{job_id}").json()["status"] == "queued":
        if time.time() > deadline:
            raise AssertionError("render never started")
        time.sleep(0.02)

    client.post(f"/api/jobs/{job_id}/cancel")
    finished = _await_job(client, job_id)
    assert finished["status"] == "cancelled"
    render = client.get(f"/api/renders/{body['render']['id']}").json()
    assert render["status"] == "cancelled"


def test_render_rejects_a_negative_seed(client, tmp_path):
    song = _import_song(client, tmp_path)
    r = client.post("/api/renders",
                    json={"song_id": song["id"], "config": {"seed": -3}})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_api_renders.py -v`
Expected: FAIL — 404 on `/api/renders`.

- [ ] **Step 3: Write the router**

Create `sleepmix/server/api/renders.py`:

```python
"""``/api/renders`` — start a full mix, watch it, fetch the result.

A render takes minutes, so it is a job like separation is. The database row is
created up front with status ``queued`` so the UI has something to show
immediately and so the config that produced a given file is recorded even if
the render later fails.

Output lands in ``paths.data_dir()/renders``, not the working directory — the
server has no meaningful CWD.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...config import MixConfig
from ...paths import data_dir
from ...pipeline import run_pipeline

router = APIRouter(prefix="/api/renders", tags=["renders"])


class RenderRequest(BaseModel):
    song_id: str
    config: dict | None = None
    preset_id: str | None = None


def _renders_dir() -> str:
    path = os.path.join(str(data_dir()), "renders")
    os.makedirs(path, exist_ok=True)
    return path


@router.post("", status_code=202)
def start_render(body: RenderRequest, request: Request) -> dict:
    store = request.app.state.store
    song = store.get_song(body.song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")

    raw_config = body.config
    if raw_config is None and body.preset_id:
        preset = next((p for p in store.list_presets() if p["id"] == body.preset_id), None)
        if preset is None:
            raise HTTPException(status_code=404, detail="No such preset")
        raw_config = preset["config"]

    try:
        config = MixConfig.from_dict(raw_config) if raw_config else MixConfig()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    render = store.add_render(song_id=body.song_id, config=raw_config or {},
                              path="", status="queued")
    output_path = os.path.join(_renders_dir(), f"{render['id']}.wav")
    store.update_render(render["id"], path=output_path)
    source = song["path"]

    def work(reporter, cancel) -> dict:
        store.update_render(render["id"], status="running")
        try:
            mix = run_pipeline(source, config, output_path,
                               reporter=reporter, cancel=cancel)
        except Exception:
            # Covers Cancelled (which is an Exception) as well as genuine
            # failures. The job manager decides which it was; either way the
            # row must not stay "running" and a partial file must not
            # masquerade as a finished render.
            status = "cancelled" if cancel is not None and cancel.cancelled else "failed"
            store.update_render(render["id"], status=status)
            if os.path.exists(output_path):
                os.remove(output_path)
            raise
        store.update_render(render["id"], status="done",
                            duration_min=mix.duration / 60.0)
        return {"render_id": render["id"], "path": output_path}

    job = request.app.state.jobs.submit("render", work, song_id=body.song_id)
    return {"job": job.as_event(), "render": store.get_render(render["id"])}


@router.get("")
def list_renders(request: Request) -> dict:
    return {"renders": request.app.state.store.list_renders()}


@router.get("/{render_id}")
def get_render(render_id: str, request: Request) -> dict:
    render = request.app.state.store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    return render


@router.get("/{render_id}/audio")
def get_render_audio(render_id: str, request: Request) -> FileResponse:
    render = request.app.state.store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    if render["status"] != "done" or not os.path.isfile(render["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"No audio for this render (status: {render['status']})")
    return FileResponse(render["path"], media_type="audio/wav",
                        filename=f"{render_id}.wav")
```

- [ ] **Step 4: Mount it**

In `sleepmix/server/app.py`, add `renders` to the `from .api import ...` line and `app.include_router(renders.router)`.

- [ ] **Step 5: Run the tests**

Run: `pipenv run pytest tests/test_api_renders.py -v`
Expected: PASS (7 tests). The cancellation test renders a 30-minute mix and cancels it partway; it should finish in seconds, not minutes — if it takes minutes, cancellation is not reaching the iteration loop and that is a real defect, not a slow test.

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/server tests/test_api_renders.py
git commit -m "feat: render endpoints with cancellation and download"
```

---

### Task 7: `/api/presets`

**Files:**
- Create: `sleepmix/server/api/presets.py`
- Modify: `sleepmix/server/app.py` (mount)
- Test: `tests/test_api_presets.py` (new)

**Interfaces:**
- Consumes: `Store.add_preset`, `.list_presets`, `.delete_preset`
- Produces:
  - `GET /api/presets` → `{"presets": [...]}`
  - `POST /api/presets` body `{name, config}` → `201`, `409` on a duplicate name
  - `DELETE /api/presets/{preset_id}` → `204`, `404` if absent

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_presets.py`:

```python
import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_create_and_list(client):
    r = client.post("/api/presets",
                    json={"name": "Slow", "config": {"tempo": {"speed": 0.5}}})
    assert r.status_code == 201
    assert r.json()["config"]["tempo"]["speed"] == 0.5
    names = [p["name"] for p in client.get("/api/presets").json()["presets"]]
    assert names == ["Slow"]


def test_duplicate_names_are_rejected(client):
    client.post("/api/presets", json={"name": "Slow", "config": {}})
    r = client.post("/api/presets", json={"name": "Slow", "config": {}})
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_delete(client):
    created = client.post("/api/presets", json={"name": "Slow", "config": {}}).json()
    assert client.delete(f"/api/presets/{created['id']}").status_code == 204
    assert client.get("/api/presets").json()["presets"] == []


def test_deleting_an_unknown_preset_404s(client):
    assert client.delete("/api/presets/nope").status_code == 404


def test_an_invalid_config_is_rejected_on_save(client):
    """Saving a preset that could never render is worse than refusing it."""
    r = client.post("/api/presets", json={"name": "Bad", "config": {"seed": -1}})
    assert r.status_code == 400
    assert "seed" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_api_presets.py -v`
Expected: FAIL — 404 on `/api/presets`.

- [ ] **Step 3: Write the router**

Create `sleepmix/server/api/presets.py`:

```python
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
```

- [ ] **Step 4: Mount it**

In `sleepmix/server/app.py`, add `presets` to the `from .api import ...` line and `app.include_router(presets.router)`.

- [ ] **Step 5: Run the tests**

Run: `pipenv run pytest tests/test_api_presets.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/server tests/test_api_presets.py
git commit -m "feat: preset CRUD with validation on save"
```

---

### Task 8: Residual fixes and documentation

**Files:**
- Modify: `sleepmix/cli.py`
- Modify: `sleepmix/server/store.py`
- Modify: `tests/test_api_songs.py`
- Modify: `docs/architecture.md`, `docs/project-state.md`, `README.md`

Four small items were carried out of the previous plan's final review, plus documentation.

- [ ] **Step 1: Make the loopback check accurate**

`sleepmix/cli.py` refuses a non-loopback `--host` by comparing against a fixed set of strings, and its message says "that is not a loopback address" — which is literally false for spellings it rejects, like `0:0:0:0:0:0:0:1`. Replace the set membership with a real check:

```python
def _is_loopback(host: str) -> bool:
    """True for any spelling of localhost.

    A string set gets this wrong: `::1`, `0:0:0:0:0:0:0:1` and `127.0.0.2` are
    all loopback and all miss a naive allow-list."""
    import ipaddress

    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
```

Use it in place of the `_LOOPBACK_HOSTS` membership test, and move the constant (if any remains) below the imports so it stops triggering E402 for the imports beneath it. Add a test asserting `--host ::1` is *accepted* and `--host 0.0.0.0` is refused.

- [ ] **Step 2: Cover the non-finite peak path through the API**

The NaN/Inf coercion in `sleepmix/peaks.py` is covered at the function level but nothing drives it through `/api/songs/{id}/peaks`. Add to `tests/test_api_songs.py`:

```python
def test_peaks_are_finite_for_a_file_containing_nan(client, tmp_path):
    """A single bad sample must not blank the whole waveform in the UI.

    Non-finite floats serialize as JSON `null`, which fails an Elm decoder for
    `list (list float)` and takes the entire waveform with it."""
    import json

    import soundfile as sf

    path = tmp_path / "nan.wav"
    y = np.zeros((2048, 2), dtype=np.float32)
    y[100] = np.nan
    y[200] = np.inf
    sf.write(str(path), y, 22050, subtype="FLOAT")

    song = client.post("/api/songs", json={"path": str(path)}).json()
    body = client.get(f"/api/songs/{song['id']}/peaks?buckets=32").json()
    assert "null" not in json.dumps(body["peaks"])
    assert all(np.isfinite(p).all() for p in body["peaks"])
```

- [ ] **Step 3: Add a unique index on song paths**

Importing the same file twice currently creates two rows with separate ids and separate render histories. Make `add_song` return the existing row instead. In `sleepmix/server/store.py`, add to `_SCHEMA`:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS songs_path_unique ON songs (path);
```

and change `add_song` to look first:

```python
    def add_song(self, path: str, title: str, duration_s: float,
                 sample_rate: int) -> dict:
        """Register a song, or return the existing row for the same path.

        Importing twice used to make two rows with separate ids and separate
        render histories, which reads as a duplicate in the library and splits
        a song's renders across two entries."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM songs WHERE path = ?", (path,)).fetchone()
            if row is not None:
                return _song_from_row(row)
            row_id = _new_id()
            self._conn.execute(
                "INSERT INTO songs (id, path, title, duration_s, sample_rate, added_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row_id, path, title, float(duration_s), int(sample_rate), _now()))
            self._conn.commit()
            return self._get_song_locked(row_id)
```

`add_song` currently calls `self.get_song(row_id)`, which re-enters the `RLock` — fine, but extract a `_get_song_locked` private helper for clarity and use it here. Add a test asserting a second import of the same path returns the same id.

- [ ] **Step 4: Correct the over-claim in project-state**

`docs/project-state.md` says `_save_fallback_reason`'s `reason is None → os.remove` branch is unreachable. It is reachable: the partial-write case its own docstring names (marker written, `_save_cache` then fails) leaves a marker with no `.wav` files, so `_load_cache` returns `None` and a later successful run does reach the removal. With `invalidate_cache` added in Task 3 it is reachable a second way. Correct the wording; the conclusion (keep the branch) was right.

- [ ] **Step 5: Extend `docs/architecture.md`**

Add a section covering, grounded in the code you just wrote: why jobs run on a single worker and what that implies for a user who starts two renders; how progress crosses the thread boundary (`call_soon_threadsafe` into per-subscriber queues) and why that is the only safe route; why the SSE stream sends a snapshot immediately to a late subscriber; why the session registry is capped and what gets evicted; and why previews return bytes rather than a URL.

- [ ] **Step 6: Update `docs/project-state.md`**

Record that Plan 2b is complete and the API is now feature-complete for Plan 3. Remove the four items this plan resolved (sticky separation cache, duplicate song rows, seed validation, the two test-coverage nits) rather than leaving them listed. Record what remains: `load_audio` still decodes the whole file per `/peaks` request with no caching and no streaming, so a very long file is a memory spike; DNS-rebinding protection is still absent and `TrustedHostMiddleware` needs care because `TestClient` uses a `testserver` Host header; and there is still no authentication of any kind, by design, for a loopback tool.

- [ ] **Step 7: Update `README.md`**

Replace the "UI (early)" section's claim that nothing renders audio yet — it does now. Describe what the API can do end to end (import, separate, preview a point in the arc, render, download) and that the interface itself is still Plan 3. Keep the localhost warning.

- [ ] **Step 8: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 9: Exercise it by hand**

Start the server (`pipenv run sleepmix ui --no-open`), then in another shell import a real song, separate it, preview a point, and start a short render — following the endpoints as a Plan 3 developer would. Paste the actual commands and responses into your report. This is the only end-to-end check that the pieces fit together as a workflow rather than individually.

- [ ] **Step 10: Commit**

```bash
git add sleepmix docs README.md tests
git commit -m "fix: carried review items; docs for the interactive server"
```

---

## What this plan does not cover

**Plan 3 — the Elm application:** `ui/` sources, `ports/audio.js` (fetching `/api/preview`, `decodeAudioData`, gapless loop swapping), `ports/events.js` (the `EventSource` bridge), and replacing `sleepmix/static/index.html` with the compiled bundle.

**Deliberately deferred beyond Plan 3:**

- Segment selection and arrangement. `LoopConfig.start_s`/`end_s` is the seam; multi-segment breaks the one-loop-repeated model in `pipeline.py` and `disintegration.py` and needs its own design.
- A path allow-list for `import_song`. `--allow-remote` is informed consent, not a mitigation.
- Streaming peak computation (`soundfile.blocks`) to remove the per-request memory spike.
- Auth of any kind.
