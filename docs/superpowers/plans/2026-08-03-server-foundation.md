# sleepmix Server Foundation Implementation Plan (Plan 2a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local FastAPI server with a SQLite library, exposing songs, the config schema, and waveform peaks — enough for the Elm Library and Song View screens to be built against.

**Architecture:** `sleepmix/server/` is a transport over the existing core and holds no DSP knowledge. FastAPI and uvicorn are an optional `[ui]` extra, imported only inside `sleepmix/server/`, so `import sleepmix` keeps working without them. Persistence is stdlib `sqlite3` behind a thin `Store`, living under the app-data directory `paths.py` already resolves.

**Tech Stack:** Python ≥3.10, FastAPI, uvicorn, stdlib `sqlite3`, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-03-sleepmix-ui-design.md`
**Preceded by:** `docs/superpowers/plans/2026-08-03-core-hooks.md` (Plan 1, complete and merged)

## Global Constraints

- Python ≥3.10 (`requires-python` in `pyproject.toml`). No 3.11+ syntax.
- **The core must stay importable without the server dependencies.** `fastapi`, `uvicorn` and `starlette` may be imported only inside `sleepmix/server/`, never from `sleepmix/*.py`. `import sleepmix` must work with only the base dependencies installed.
- Optional dependencies (`librosa`, `demucs`, `torch`, `pedalboard`, `pyrubberband`) must never be imported at module scope anywhere.
- Audio is always float32, shape `(n_frames, n_channels)`.
- **The server holds no business logic.** It is a transport over the core. Anything that computes audio belongs in `sleepmix/*.py`, not `sleepmix/server/*.py`.
- All persistent state lives under `paths.data_dir()`. Nothing may write to the current working directory.
- **Tests must never touch the operator's real data directory.** `tests/conftest.py` already sets `SLEEPMIX_DATA_DIR` to a tmpdir via an autouse fixture; anything reaching the filesystem must route through `paths.py` so it inherits that isolation.
- Existing style: module docstring explaining *why*, `from __future__ import annotations`, private helpers prefixed `_`.
- The CLI must keep working unchanged. `sleepmix render` and `sleepmix init-config` behaviour and output are untouched.

## File Structure

| File | Responsibility |
|---|---|
| `sleepmix/server/__init__.py` | Package marker; no imports with side effects |
| `sleepmix/server/app.py` | FastAPI app factory, router mounting, static files |
| `sleepmix/server/store.py` | SQLite persistence — the only module that writes SQL |
| `sleepmix/server/api/schema.py` | `/api/schema` |
| `sleepmix/server/api/songs.py` | `/api/songs*` |
| `sleepmix/peaks.py` | Waveform peak computation (core — pure numpy over an `AudioBuffer`) |
| `sleepmix/separation.py` | Gains `SeparationResult` / `separate_detailed` |
| `sleepmix/cli.py` | Gains the `ui` command |

`peaks.py` is core rather than server because it is pure numpy over an `AudioBuffer`, is testable without HTTP, and is useful from the Python API. The server merely serves it.

---

### Task 1: The `[ui]` extra, app factory, and `sleepmix ui`

**Files:**
- Modify: `pyproject.toml` (optional-dependencies)
- Modify: `Pipfile` (dev environment)
- Create: `sleepmix/server/__init__.py`
- Create: `sleepmix/server/app.py`
- Modify: `sleepmix/cli.py` (add the `ui` command)
- Test: `tests/test_server_app.py`

**Interfaces:**
- Consumes: `sleepmix.__version__`
- Produces:
  - `sleepmix.server.app.create_app() -> FastAPI`
  - `GET /api/health` → `{"status": "ok", "version": str}`
  - CLI `sleepmix ui [--host] [--port] [--open/--no-open]`

- [ ] **Step 1: Add the optional dependency group**

In `pyproject.toml`, add to `[project.optional-dependencies]`:

```toml
ui = ["fastapi>=0.110", "uvicorn>=0.27"]
```

And extend the `dev` group so the test suite can exercise the server:

```toml
dev = ["pytest>=7.4", "fastapi>=0.110", "uvicorn>=0.27", "httpx>=0.27"]
```

`httpx` is required by FastAPI's `TestClient`.

- [ ] **Step 2: Install into the dev environment**

Run: `pipenv install --dev`
Expected: fastapi, uvicorn and httpx resolve and install.

Verify: `pipenv run python -c "import fastapi, uvicorn, httpx; print('ok')"` prints `ok`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_server_app.py`:

```python
import subprocess
import sys

from fastapi.testclient import TestClient

import sleepmix
from sleepmix.server.app import create_app


def test_health_reports_status_and_version():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    # Subset rather than exact equality: Task 6 adds a "warm" field, and a
    # health endpoint growing a key should not break an unrelated test.
    assert body["status"] == "ok"
    assert body["version"] == sleepmix.__version__


def test_unknown_api_route_is_404():
    client = TestClient(create_app())
    assert client.get("/api/nope").status_code == 404


def test_core_imports_without_server_dependencies():
    """`import sleepmix` must not pull in fastapi.

    The server deps are an optional extra; someone who installed only the base
    package must still be able to use the CLI and the Python API."""
    code = (
        "import sys; import sleepmix; "
        "assert 'fastapi' not in sys.modules, sorted(m for m in sys.modules if 'fastapi' in m); "
        "print('clean')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "clean" in out.stdout


def test_ui_command_is_registered():
    from click.testing import CliRunner

    from sleepmix.cli import main

    result = CliRunner().invoke(main, ["ui", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_server_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server'`

- [ ] **Step 5: Create the server package**

Create `sleepmix/server/__init__.py`:

```python
"""HTTP transport over the sleepmix core.

Everything in this package is a thin adapter: it decodes a request, calls into
``sleepmix.*``, and encodes the result. No audio processing lives here — that
keeps the CLI and the Python API first-class rather than degraded citizens of
the UI, and it keeps the core testable without starting a server.

FastAPI and uvicorn are an optional extra (``pip install "sleepmix[ui]"``) and
are imported only from inside this package.
"""
from __future__ import annotations
```

- [ ] **Step 6: Write the app factory**

Create `sleepmix/server/app.py`:

```python
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
```

- [ ] **Step 7: Add the `ui` command**

In `sleepmix/cli.py`, append this command (keep the existing imports and commands untouched):

```python
@main.command()
@click.option("--host", default="127.0.0.1", help="Interface to bind.")
@click.option("--port", default=8765, type=int, help="Port to bind.")
@click.option("--open/--no-open", "open_browser", default=True,
              help="Open a browser tab on start.")
def ui(host, port, open_browser):
    """Start the local web UI."""
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "The UI needs extra dependencies. Install them with:\n"
            "    pip install \"sleepmix[ui]\""
        )
    from .server.app import create_app

    if open_browser:
        import threading
        import webbrowser

        threading.Timer(
            1.0, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
```

The `uvicorn` import is inside the function so `sleepmix --help` still works without the extra installed.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_server_app.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, 69 tests.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml Pipfile Pipfile.lock sleepmix/server sleepmix/cli.py tests/test_server_app.py
git commit -m "feat: FastAPI app factory and sleepmix ui command"
```

---

### Task 2: `store.py` — SQLite persistence

**Files:**
- Create: `sleepmix/server/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `sleepmix.paths.data_dir()`
- Produces: `Store` with
  - `Store(db_path: str | None = None)` — defaults to `paths.data_dir()/library.db`
  - `.add_song(path: str, title: str, duration_s: float, sample_rate: int) -> dict`
  - `.list_songs() -> list[dict]`
  - `.get_song(song_id: str) -> dict | None`
  - `.update_song(song_id: str, **fields) -> dict | None`
  - `.add_preset(name: str, config: dict) -> dict`
  - `.list_presets() -> list[dict]`
  - `.delete_preset(preset_id: str) -> bool`
  - `.add_render(song_id: str, config: dict, path: str, status: str) -> dict`
  - `.list_renders() -> list[dict]`
  - `.get_render(render_id: str) -> dict | None`
  - `.update_render(render_id: str, **fields) -> dict | None`
  - `.close() -> None`

All methods return plain JSON-ready dicts. `config` round-trips as a parsed dict.

- [ ] **Step 1: Write the failing test**

Create `tests/test_store.py`:

```python
import pytest

from sleepmix import paths
from sleepmix.server.store import Store


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


def test_database_lives_under_the_data_dir(store):
    assert str(paths.data_dir()) in store.db_path


def test_add_and_get_song_round_trips(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=12.5, sample_rate=44100)
    assert song["id"]
    assert song["separation_status"] == "pending"
    fetched = store.get_song(song["id"])
    assert fetched["title"] == "A"
    assert fetched["duration_s"] == 12.5
    assert fetched["sample_rate"] == 44100


def test_get_song_returns_none_when_absent(store):
    assert store.get_song("nope") is None


def test_list_songs_is_newest_first(store):
    a = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    b = store.add_song(path="/tmp/b.wav", title="B", duration_s=1.0, sample_rate=44100)
    ids = [s["id"] for s in store.list_songs()]
    assert ids.index(b["id"]) < ids.index(a["id"])


def test_update_song_changes_only_named_fields(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    updated = store.update_song(song["id"], separation_status="failed",
                                separation_reason="Demucs not installed")
    assert updated["separation_status"] == "failed"
    assert updated["separation_reason"] == "Demucs not installed"
    assert updated["title"] == "A"


def test_update_song_rejects_unknown_columns(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    with pytest.raises(ValueError):
        store.update_song(song["id"], nonsense="x")


def test_update_song_returns_none_when_absent(store):
    assert store.update_song("nope", title="x") is None


def test_presets_round_trip_config_as_a_dict(store):
    p = store.add_preset("Slow", {"tempo": {"speed": 0.5}})
    assert p["config"] == {"tempo": {"speed": 0.5}}
    assert store.list_presets()[0]["config"]["tempo"]["speed"] == 0.5
    assert store.delete_preset(p["id"]) is True
    assert store.list_presets() == []
    assert store.delete_preset(p["id"]) is False


def test_preset_names_are_unique(store):
    store.add_preset("Slow", {})
    with pytest.raises(ValueError):
        store.add_preset("Slow", {})


def test_renders_round_trip(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    r = store.add_render(song_id=song["id"], config={"seed": 3},
                         path="/tmp/out.wav", status="running")
    assert r["config"] == {"seed": 3}
    assert store.get_render(r["id"])["status"] == "running"
    assert store.update_render(r["id"], status="done")["status"] == "done"
    assert [x["id"] for x in store.list_renders()] == [r["id"]]


def test_a_second_store_sees_the_first_store_s_data(store):
    song = store.add_song(path="/tmp/a.wav", title="A", duration_s=1.0, sample_rate=44100)
    other = Store()
    try:
        assert other.get_song(song["id"])["title"] == "A"
    finally:
        other.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server.store'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/server/store.py`:

```python
"""SQLite persistence for the library: songs, presets and renders.

Stdlib ``sqlite3`` behind a thin wrapper rather than an ORM — the schema is
three flat tables and the project's style is plain dataclasses and light
dependencies, so SQLAlchemy would be more machinery than the problem needs.

Config is stored as a JSON blob rather than exploded into columns. ``MixConfig``
already round-trips through dicts, and a normalized schema would need migrating
every time a decay parameter is added.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ..paths import data_dir

_SONG_COLUMNS = {"path", "title", "duration_s", "sample_rate",
                 "separation_status", "separation_reason", "stems"}
_RENDER_COLUMNS = {"song_id", "config", "path", "status", "duration_min"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id                 TEXT PRIMARY KEY,
    path               TEXT NOT NULL,
    title              TEXT NOT NULL,
    duration_s         REAL NOT NULL,
    sample_rate        INTEGER NOT NULL,
    separation_status  TEXT NOT NULL DEFAULT 'pending',
    separation_reason  TEXT,
    stems              TEXT,
    added_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS presets (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    config     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS renders (
    id           TEXT PRIMARY KEY,
    song_id      TEXT NOT NULL,
    config       TEXT NOT NULL,
    path         TEXT NOT NULL,
    status       TEXT NOT NULL,
    duration_min REAL,
    created_at   TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class Store:
    """The library database. One instance per app; safe to open several."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or str(data_dir() / "library.db")
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- songs ----------------------------------------------------------
    def add_song(self, path: str, title: str, duration_s: float,
                 sample_rate: int) -> dict:
        row_id = _new_id()
        self._conn.execute(
            "INSERT INTO songs (id, path, title, duration_s, sample_rate, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (row_id, path, title, float(duration_s), int(sample_rate), _now()))
        self._conn.commit()
        return self.get_song(row_id)

    def get_song(self, song_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        return _song_from_row(row)

    def list_songs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM songs ORDER BY added_at DESC, rowid DESC").fetchall()
        return [_song_from_row(r) for r in rows]

    def update_song(self, song_id: str, **fields: Any) -> dict | None:
        unknown = set(fields) - _SONG_COLUMNS
        if unknown:
            raise ValueError(f"unknown song columns: {sorted(unknown)}")
        if self.get_song(song_id) is None:
            return None
        if fields:
            if "stems" in fields and not isinstance(fields["stems"], str):
                fields["stems"] = json.dumps(fields["stems"])
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self._conn.execute(
                f"UPDATE songs SET {assignments} WHERE id = ?",
                (*fields.values(), song_id))
            self._conn.commit()
        return self.get_song(song_id)

    # -- presets --------------------------------------------------------
    def add_preset(self, name: str, config: dict) -> dict:
        row_id = _new_id()
        try:
            self._conn.execute(
                "INSERT INTO presets (id, name, config, created_at) VALUES (?, ?, ?, ?)",
                (row_id, name, json.dumps(config), _now()))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"a preset named {name!r} already exists") from exc
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM presets WHERE id = ?", (row_id,)).fetchone()
        return _preset_from_row(row)

    def list_presets(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM presets ORDER BY name").fetchall()
        return [_preset_from_row(r) for r in rows]

    def delete_preset(self, preset_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # -- renders --------------------------------------------------------
    def add_render(self, song_id: str, config: dict, path: str, status: str) -> dict:
        row_id = _new_id()
        self._conn.execute(
            "INSERT INTO renders (id, song_id, config, path, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (row_id, song_id, json.dumps(config), path, status, _now()))
        self._conn.commit()
        return self.get_render(row_id)

    def get_render(self, render_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM renders WHERE id = ?", (render_id,)).fetchone()
        return _render_from_row(row)

    def list_renders(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM renders ORDER BY created_at DESC, rowid DESC").fetchall()
        return [_render_from_row(r) for r in rows]

    def update_render(self, render_id: str, **fields: Any) -> dict | None:
        unknown = set(fields) - _RENDER_COLUMNS
        if unknown:
            raise ValueError(f"unknown render columns: {sorted(unknown)}")
        if self.get_render(render_id) is None:
            return None
        if fields:
            if "config" in fields and not isinstance(fields["config"], str):
                fields["config"] = json.dumps(fields["config"])
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self._conn.execute(
                f"UPDATE renders SET {assignments} WHERE id = ?",
                (*fields.values(), render_id))
            self._conn.commit()
        return self.get_render(render_id)


# -- row adapters -------------------------------------------------------
def _song_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["stems"] = json.loads(d["stems"]) if d["stems"] else None
    return d


def _preset_from_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d


def _render_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config"])
    return d
```

The `f"{assignments}"` interpolation is safe: `fields` keys are validated against a fixed allow-list before use, and every value is passed as a bound parameter.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_store.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sleepmix/server/store.py tests/test_store.py
git commit -m "feat: SQLite library store for songs, presets and renders"
```

---

### Task 3: `separate_detailed` — surface why separation fell back

**Files:**
- Modify: `sleepmix/separation.py`
- Test: `tests/test_separation.py` (new)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `SeparationResult` dataclass: `.stems: dict[str, AudioBuffer]`, `.fallback_reason: str | None`
  - `separate_detailed(input_path, model="htdemucs_ft", cache_dir=".sleepmix_cache") -> SeparationResult`
  - `separate(...)` keeps its existing signature and return type (`dict[str, AudioBuffer]`), now implemented as `separate_detailed(...).stems`

**Why this matters:** `separation.py` currently catches every exception and falls back to a single `mix` stem with only a `warnings.warn`. In a terminal that is visible; in a UI it is not — a user would configure per-stem decay curves, receive one undifferentiated stem, and get no explanation. The reason must become data.

- [ ] **Step 1: Write the failing test**

Create `tests/test_separation.py`:

```python
import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.separation import SeparationResult, separate, separate_detailed


def _song(path, sr=22050, secs=2.0):
    t = np.arange(int(sr * secs)) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))


def test_fallback_reports_a_reason(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))

    result = separate_detailed(str(song), cache_dir=str(tmp_path / "cache"))
    assert isinstance(result, SeparationResult)
    assert set(result.stems) == {"mix"}
    assert result.fallback_reason is not None
    assert "no torch" in result.fallback_reason


def test_fallback_reason_survives_a_cache_hit(tmp_path, monkeypatch):
    """A cached fallback must still report itself as a fallback.

    Otherwise the second load looks like a successful separation and the UI
    stops explaining why there is only one stem."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))

    first = separate_detailed(str(song), cache_dir=cache)
    second = separate_detailed(str(song), cache_dir=cache)
    assert first.fallback_reason is not None
    assert second.fallback_reason == first.fallback_reason


def test_successful_separation_has_no_reason(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    song = tmp_path / "s.wav"
    _song(song)

    def fake(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", fake)
    result = separate_detailed(str(song), cache_dir=str(tmp_path / "cache"))
    assert result.fallback_reason is None
    assert set(result.stems) == {"vocals", "drums", "bass", "other"}


def test_separate_keeps_its_dict_contract(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("nope")))

    stems = separate(str(song), cache_dir=str(tmp_path / "cache"))
    assert isinstance(stems, dict)
    assert set(stems) == {"mix"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_separation.py -v`
Expected: FAIL — `ImportError: cannot import name 'SeparationResult'`

- [ ] **Step 3: Write the implementation**

In `sleepmix/separation.py`, add to the imports:

```python
from dataclasses import dataclass
```

Add the result type above `separate`:

```python
_FALLBACK_MARKER = "fallback.txt"


@dataclass
class SeparationResult:
    """Stems, plus why they might not be what you asked for.

    The fallback used to be announced only through ``warnings.warn``, which a
    terminal shows and a UI swallows — leaving someone to configure per-stem
    decay, receive one undifferentiated stem, and get no explanation. The reason
    is data now, and it is cached alongside the stems so a later load still
    knows it is looking at a fallback."""

    stems: dict[str, AudioBuffer]
    fallback_reason: str | None = None
```

Replace `separate` with:

```python
def separate(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> dict[str, AudioBuffer]:
    """Return a dict of stem-name -> AudioBuffer for ``input_path``."""
    return separate_detailed(input_path, model, cache_dir).stems


def separate_detailed(
    input_path: str,
    model: str = "htdemucs_ft",
    cache_dir: str = ".sleepmix_cache",
) -> SeparationResult:
    """Like ``separate``, but also reports why it fell back, if it did."""
    key = _cache_key(input_path, model)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return SeparationResult(cached, _load_fallback_reason(cache_dir, key))

    reason: str | None = None
    try:
        stems = _demucs_separate(input_path, model)
    except Exception as exc:  # noqa: BLE001 - intentional broad fallback
        reason = (
            f"Demucs separation unavailable ({exc}); using the full mix as a "
            f"single 'mix' stem. Install the 'separation' extra for real stems."
        )
        warnings.warn(reason, stacklevel=2)
        stems = {"mix": load_audio(input_path)}

    _save_cache(cache_dir, key, stems)
    _save_fallback_reason(cache_dir, key, reason)
    return SeparationResult(stems, reason)
```

Add the marker helpers next to the other cache helpers:

```python
def _fallback_marker_path(cache_dir: str, key: str) -> str:
    return os.path.join(_cache_path(cache_dir, key), _FALLBACK_MARKER)


def _save_fallback_reason(cache_dir: str, key: str, reason: str | None) -> None:
    path = _fallback_marker_path(cache_dir, key)
    if reason is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w") as fh:
        fh.write(reason)


def _load_fallback_reason(cache_dir: str, key: str) -> str | None:
    path = _fallback_marker_path(cache_dir, key)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return fh.read() or None
```

`_load_cache` iterates `*.wav` only, so the marker file does not become a stem.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_separation.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS. `tests/test_pipeline.py::test_full_render_fallback` still exercises the fallback and must remain green.

- [ ] **Step 6: Commit**

```bash
git add sleepmix/separation.py tests/test_separation.py
git commit -m "feat: report why stem separation fell back, and cache the reason"
```

---

### Task 4: `peaks.py` — waveform peak computation

**Files:**
- Create: `sleepmix/peaks.py`
- Modify: `sleepmix/__init__.py` (export `compute_peaks`)
- Test: `tests/test_peaks.py`

**Interfaces:**
- Consumes: `AudioBuffer`
- Produces: `compute_peaks(buf: AudioBuffer, buckets: int = 2000) -> list[list[float]]` — one `[min, max]` pair per bucket, computed on the mono downmix

**Why server-side:** shipping a 40 MB WAV to the browser so it can decode and scan it would stall the page for no benefit. The server already has the audio decoded.

- [ ] **Step 1: Write the failing test**

Create `tests/test_peaks.py`:

```python
import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.peaks import compute_peaks


def _buf(y, sr=22050):
    arr = np.asarray(y, dtype=np.float32)
    return AudioBuffer(np.stack([arr, arr], axis=1), sr)


def test_returns_one_min_max_pair_per_bucket():
    peaks = compute_peaks(_buf(np.sin(np.linspace(0, 100, 10000))), buckets=50)
    assert len(peaks) == 50
    assert all(len(p) == 2 for p in peaks)
    assert all(p[0] <= p[1] for p in peaks)


def test_tracks_a_rising_envelope():
    """A ramp must produce buckets whose maxima increase."""
    ramp = np.linspace(0.0, 1.0, 10000)
    peaks = compute_peaks(_buf(ramp), buckets=10)
    maxima = [p[1] for p in peaks]
    assert maxima == sorted(maxima)
    assert maxima[-1] > maxima[0]


def test_captures_sign_of_the_signal():
    y = np.concatenate([np.full(5000, -0.5), np.full(5000, 0.5)])
    peaks = compute_peaks(_buf(y), buckets=2)
    assert peaks[0][0] < 0 and peaks[0][1] < 0.01
    assert peaks[1][1] > 0


def test_short_buffer_does_not_produce_empty_buckets():
    """Fewer frames than buckets must still yield well-formed pairs."""
    peaks = compute_peaks(_buf(np.linspace(-1, 1, 7)), buckets=100)
    assert len(peaks) == 100
    assert all(np.isfinite(p).all() for p in peaks)


def test_empty_buffer_returns_zeroed_pairs():
    peaks = compute_peaks(AudioBuffer(np.zeros((0, 2), dtype=np.float32), 44100), buckets=8)
    assert peaks == [[0.0, 0.0]] * 8


def test_values_are_json_serializable_floats():
    import json

    peaks = compute_peaks(_buf(np.sin(np.linspace(0, 10, 1000))), buckets=16)
    json.dumps(peaks)  # must not raise on numpy scalars
    assert isinstance(peaks[0][0], float)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_peaks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.peaks'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/peaks.py`:

```python
"""Waveform summary for display.

A UI drawing a waveform needs a few thousand min/max pairs, not forty megabytes
of samples. Computing them here means the browser receives a small JSON array
instead of decoding an entire WAV to scan it.

Min *and* max are kept rather than absolute peak so the drawn waveform stays
signed — an asymmetric signal looks asymmetric, which is a real cue when you are
picking a loop region by eye.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer


def compute_peaks(buf: AudioBuffer, buckets: int = 2000) -> list[list[float]]:
    """Return ``buckets`` ``[min, max]`` pairs across the whole buffer."""
    buckets = max(int(buckets), 1)
    if buf.n_frames == 0:
        return [[0.0, 0.0] for _ in range(buckets)]

    mono = buf.to_mono().data[:, 0]
    # Bucket boundaries by index rather than a reshape, so a buffer that does
    # not divide evenly (or is shorter than `buckets`) still yields one pair per
    # bucket instead of dropping the remainder.
    edges = np.linspace(0, mono.shape[0], buckets + 1).astype(int)
    out: list[list[float]] = []
    for i in range(buckets):
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            # Fewer frames than buckets: repeat the nearest sample rather than
            # emitting an empty bucket.
            lo = min(lo, mono.shape[0] - 1)
            hi = lo + 1
        segment = mono[lo:hi]
        out.append([float(segment.min()), float(segment.max())])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_peaks.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Export it**

In `sleepmix/__init__.py`, add the import alongside the existing ones:

```python
from .peaks import compute_peaks
```

and extend `__all__`:

```python
__all__ += ["compute_peaks"]
```

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/peaks.py sleepmix/__init__.py tests/test_peaks.py
git commit -m "feat: server-side waveform peak computation"
```

---

### Task 5: `/api/schema` and the songs API

**Files:**
- Create: `sleepmix/server/api/__init__.py`
- Create: `sleepmix/server/api/schema.py`
- Create: `sleepmix/server/api/songs.py`
- Modify: `sleepmix/server/app.py` (mount routers, hold the store)
- Test: `tests/test_api_songs.py`

**Interfaces:**
- Consumes: `Store` (Task 2), `separate_detailed` / `SeparationResult` (Task 3), `compute_peaks` (Task 4), `config_schema` (Plan 1)
- Produces:
  - `GET /api/schema` → the `config_schema()` dict
  - `POST /api/songs` body `{"path": str}` → song dict, 201
  - `GET /api/songs` → `{"songs": [...]}`
  - `GET /api/songs/{id}` → song dict, 404 if absent
  - `GET /api/songs/{id}/peaks?buckets=N` → `{"peaks": [[min,max], ...], "duration_s": float}`
  - `app.state.store` — the `Store` instance, so later tasks and tests can reach it

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_songs.py`:

```python
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _song_file(path, sr=22050, secs=3.0):
    t = np.arange(int(sr * secs)) / sr
    y = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))
    return str(path)


def test_schema_endpoint_returns_config_metadata(client):
    from sleepmix.config import config_schema

    r = client.get("/api/schema")
    assert r.status_code == 200
    assert r.json() == config_schema()


def test_import_song_records_duration_and_rate(client, tmp_path):
    path = _song_file(tmp_path / "a.wav")
    r = client.post("/api/songs", json={"path": path})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "a"
    assert body["sample_rate"] == 22050
    assert abs(body["duration_s"] - 3.0) < 0.05
    assert body["separation_status"] == "pending"


def test_import_rejects_a_missing_file(client, tmp_path):
    r = client.post("/api/songs", json={"path": str(tmp_path / "nope.wav")})
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()


def test_import_rejects_a_file_that_is_not_audio(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not audio")
    r = client.post("/api/songs", json={"path": str(bad)})
    assert r.status_code == 400


def test_list_songs_returns_what_was_imported(client, tmp_path):
    client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")})
    client.post("/api/songs", json={"path": _song_file(tmp_path / "b.wav")})
    titles = {s["title"] for s in client.get("/api/songs").json()["songs"]}
    assert titles == {"a", "b"}


def test_get_song_404s_when_absent(client):
    assert client.get("/api/songs/nope").status_code == 404


def test_peaks_endpoint_returns_the_requested_bucket_count(client, tmp_path):
    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    r = client.get(f"/api/songs/{song['id']}/peaks?buckets=64")
    assert r.status_code == 200
    body = r.json()
    assert len(body["peaks"]) == 64
    assert all(len(p) == 2 for p in body["peaks"])
    assert abs(body["duration_s"] - 3.0) < 0.05


def test_peaks_404s_for_an_unknown_song(client):
    assert client.get("/api/songs/nope/peaks").status_code == 404


def test_peaks_rejects_an_absurd_bucket_count(client, tmp_path):
    """An unbounded bucket count would let one request allocate arbitrarily."""
    song = client.post("/api/songs", json={"path": _song_file(tmp_path / "a.wav")}).json()
    assert client.get(f"/api/songs/{song['id']}/peaks?buckets=10000000").status_code == 422


def test_peaks_404s_when_the_file_has_moved(client, tmp_path):
    path = _song_file(tmp_path / "a.wav")
    song = client.post("/api/songs", json={"path": path}).json()
    import os

    os.remove(path)
    r = client.get(f"/api/songs/{song['id']}/peaks")
    assert r.status_code == 404
    assert "unavailable" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_api_songs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server.api'`

- [ ] **Step 3: Create the api package and the schema router**

Create `sleepmix/server/api/__init__.py`:

```python
"""HTTP routers, one module per resource."""
from __future__ import annotations
```

Create `sleepmix/server/api/schema.py`:

```python
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
```

- [ ] **Step 4: Write the songs router**

Create `sleepmix/server/api/songs.py`:

```python
"""``/api/songs`` — the library's record of importable audio files.

Importing registers a *path*, it does not copy the file. This is a local tool
operating on the operator's own music; copying gigabytes into an app-data
directory would be surprising and wasteful. The cost is that a song can become
unavailable if the file moves, which is reported rather than raised.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...audio import load_audio
from ...peaks import compute_peaks

router = APIRouter(prefix="/api/songs", tags=["songs"])

MAX_PEAK_BUCKETS = 20000


class ImportRequest(BaseModel):
    path: str


@router.post("", status_code=201)
def import_song(body: ImportRequest, request: Request) -> dict:
    path = os.path.abspath(os.path.expanduser(body.path))
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    try:
        buf = load_audio(path)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad request
        raise HTTPException(
            status_code=400, detail=f"Could not read audio from {path}: {exc}")
    title = os.path.splitext(os.path.basename(path))[0]
    return request.app.state.store.add_song(
        path=path, title=title, duration_s=buf.duration, sample_rate=buf.sr)


@router.get("")
def list_songs(request: Request) -> dict:
    return {"songs": request.app.state.store.list_songs()}


@router.get("/{song_id}")
def get_song(song_id: str, request: Request) -> dict:
    song = request.app.state.store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    return song


@router.get("/{song_id}/peaks")
def get_peaks(
    song_id: str,
    request: Request,
    buckets: int = Query(default=2000, ge=1, le=MAX_PEAK_BUCKETS),
) -> dict:
    song = request.app.state.store.get_song(song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="No such song")
    if not os.path.isfile(song["path"]):
        raise HTTPException(
            status_code=404,
            detail=f"Source file unavailable — it has moved or been deleted: {song['path']}")
    buf = load_audio(song["path"])
    return {"peaks": compute_peaks(buf, buckets), "duration_s": buf.duration}
```

- [ ] **Step 5: Mount the routers and own the store**

Replace `sleepmix/server/app.py` with:

```python
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
```

Because the store is created in the lifespan handler, tests must use
`TestClient` as a context manager (`with TestClient(create_app()) as c:`) for
`app.state.store` to exist — the fixture in the test file already does.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_api_songs.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Fix the earlier app test for the lifespan change**

`tests/test_server_app.py` builds `TestClient(create_app())` without a context
manager. Update its two client-using tests to use `with TestClient(create_app()) as client:`
so the lifespan runs and the store is closed. Do not change what they assert.

- [ ] **Step 8: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add sleepmix/server tests/test_api_songs.py tests/test_server_app.py
git commit -m "feat: schema and songs API with waveform peaks"
```

---

### Task 6: Static file serving and the librosa warm-up

**Files:**
- Modify: `sleepmix/server/app.py`
- Create: `sleepmix/static/index.html` (placeholder until Plan 3)
- Create: `sleepmix/server/warmup.py`
- Modify: `pyproject.toml` (package data)
- Test: `tests/test_server_static.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `GET /` serves `sleepmix/static/index.html`
  - `warmup.warm_analysis() -> None` — forces librosa's numba compilation
  - `GET /api/health` gains `"warm": bool`

**Why the warm-up:** librosa's numba compilation is cold on first use. During development one first call exceeded a two-minute timeout while the second took 0.9 s. A UI that appears to hang for two minutes on first launch reads as broken.

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_static.py`:

```python
import pytest
from fastapi.testclient import TestClient

from sleepmix.server.app import create_app
from sleepmix.server.warmup import warm_analysis


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_root_serves_the_index_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "sleepmix" in r.text.lower()


def test_health_reports_warm_state(client):
    assert "warm" in client.get("/api/health").json()


def test_warm_analysis_sets_the_flag_and_is_idempotent():
    """Must not raise even when librosa is absent — it is an optional dep.

    Reaches into ``_warmed`` because module-level memoization is exactly what
    is under test: without resetting it, whichever test ran first would have
    already warmed the module and this would assert nothing."""
    from sleepmix.server import warmup

    warmup._warmed = False
    assert warmup.is_warm() is False
    warm_analysis()
    assert warmup.is_warm() is True
    warm_analysis()  # second call must be a no-op, not an error
    assert warmup.is_warm() is True


def test_warm_analysis_makes_the_next_loop_search_fast():
    import time

    import numpy as np

    from sleepmix.analysis import find_loop
    from sleepmix.audio import AudioBuffer
    from sleepmix.config import LoopConfig

    warm_analysis()
    sr = 22050
    t = np.arange(sr * 4) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    buf = AudioBuffer(np.stack([y, y], axis=1), sr)

    start = time.perf_counter()
    find_loop(buf, LoopConfig())
    assert time.perf_counter() - start < 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_server_static.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.server.warmup'`

- [ ] **Step 3: Write the warm-up module**

Create `sleepmix/server/warmup.py`:

```python
"""Force librosa's just-in-time compilation before a user can trigger it.

librosa leans on numba, which compiles on first call. Cold, that first call can
take minutes; warm, it is under a second. A UI that stalls for two minutes the
first time you open a song reads as broken, so the server pays that cost at
startup instead, on a throwaway buffer.

Silent when librosa is not installed — it is an optional dependency and the
pipeline degrades to a fixed-tempo loop guess without it.
"""
from __future__ import annotations

import numpy as np

_warmed = False


def is_warm() -> bool:
    return _warmed


def warm_analysis() -> None:
    """Run a tiny beat-track so the JIT compiles now rather than on first use."""
    global _warmed
    if _warmed:
        return
    try:
        import librosa

        sr = 22050
        t = np.arange(sr) / sr
        y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
        librosa.beat.beat_track(y=y, sr=sr)
    except Exception:  # noqa: BLE001 - librosa is optional; warming is best-effort
        pass
    _warmed = True
```

- [ ] **Step 4: Create the placeholder page**

Create `sleepmix/static/index.html`:

```html
<!doctype html>
<meta charset="utf-8">
<title>sleepmix</title>
<style>
  body { font: 15px/1.6 system-ui, sans-serif; max-width: 34rem;
         margin: 12vh auto; padding: 0 1.5rem; color: #ddd; background: #17181b; }
  code { background: #24262b; padding: .1em .35em; border-radius: 3px; }
</style>
<h1>sleepmix</h1>
<p>The server is running. The interface is not built yet — this page is a
placeholder that Plan 3 replaces with the compiled Elm application.</p>
<p>The API is live: try <code>/api/health</code>, <code>/api/schema</code>
or <code>/api/songs</code>.</p>
```

- [ ] **Step 5: Ship the static directory in the wheel**

In `pyproject.toml`, extend the package-data entry:

```toml
[tool.setuptools.package-data]
sleepmix = ["config.example.yaml", "static/*"]
```

Package discovery is already automatic — Task 1 set:

```toml
[tool.setuptools.packages.find]
include = ["sleepmix*"]
```

so `sleepmix.server` and `sleepmix.server.api` are picked up without being
listed. **Do not replace that with an explicit package list**; enumeration is
what caused `sleepmix.server` to be omitted from the wheel in the first place,
and an editable install cannot reveal the mistake. Only the `package-data` line
above needs changing in this step.

- [ ] **Step 6: Wire static serving and warm-up into the app**

In `sleepmix/server/app.py`, add to the imports:

```python
import asyncio
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .warmup import is_warm, warm_analysis
```

Change the lifespan handler to kick off the warm-up without blocking startup, and add the routes. The full `create_app` becomes:

```python
def create_app(store: Store | None = None) -> FastAPI:
    static_dir = Path(__file__).resolve().parent.parent / "static"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store()
        # Off the event loop: warming blocks for minutes on a cold numba cache,
        # and the UI should be able to render its shell meanwhile.
        app.state.warm_task = asyncio.create_task(asyncio.to_thread(warm_analysis))
        try:
            yield
        finally:
            app.state.warm_task.cancel()
            app.state.store.close()

    app = FastAPI(title="sleepmix", version=sleepmix.__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": sleepmix.__version__, "warm": is_warm()}

    app.include_router(schema.router)
    app.include_router(songs.router)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_server_static.py -v`
Expected: PASS (4 tests). The last one may take a while on the very first run if numba's cache is cold — that is the behaviour under test.

- [ ] **Step 8: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 9: Start the server by hand and check it**

Run: `pipenv run sleepmix ui --no-open --port 8765` in one terminal, then in another:

```bash
curl -s localhost:8765/api/health
curl -s localhost:8765/api/schema | head -c 200
curl -s localhost:8765/ | head -3
```

Expected: health returns `{"status":"ok","version":"0.1.0","warm":...}`; schema returns JSON; `/` returns the placeholder HTML. Stop the server with Ctrl-C. Record the actual output in your report.

- [ ] **Step 10: Commit**

```bash
git add sleepmix/server sleepmix/static pyproject.toml tests/test_server_static.py
git commit -m "feat: serve the static shell and warm librosa at startup"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/project-state.md`
- Modify: `README.md`

- [ ] **Step 1: Extend `docs/architecture.md`**

Add a section covering the server layer, grounded in the code you just wrote — read it rather than describing intentions. Cover: why the server holds no business logic and what that buys; why `create_app` is a factory rather than a module-level `app`; why `fastapi`/`uvicorn` are an optional extra and how `sleepmix/cli.py` degrades when they are absent; the store's schema and why config is a JSON blob rather than normalized columns; why importing a song registers a path rather than copying the file, and the consequence when a file moves; and why the warm-up exists.

- [ ] **Step 2: Update `docs/project-state.md`**

Record: that Plan 2a is complete and what it does *not* yet do (no preview, no renders, no job management, no presets endpoints — those are Plan 2b); that `sleepmix/static/index.html` is a placeholder Plan 3 replaces, which is a deliberate temporary stand-in and must not be mistaken for the finished UI; that the silent Demucs fallback is now surfaced as `separation_status`/`separation_reason` on the song row, resolving an item previously listed as deferred; and that the librosa cold-JIT stall is now warmed at startup, resolving another.

Remove the two entries those changes resolve, rather than leaving them listed as outstanding.

- [ ] **Step 3: Update `README.md`**

Add a short Usage subsection for the UI: `pip install "sleepmix[ui]"` then `sleepmix ui`, noting it opens a browser at `127.0.0.1:8765` and that the interface itself arrives in a later change. Match the README's existing register — direct, concrete, no marketing.

- [ ] **Step 4: Verify the suite is still green**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md docs/project-state.md README.md
git commit -m "docs: server foundation architecture and state"
```

---

## What this plan does not cover

Deferred to **Plan 2b** (interactive machinery):

- `server/jobs.py` — background job manager with progress and cancellation
- `server/sessions.py` — `RenderSession` registry with LRU eviction (sessions hold decoded audio; an unbounded registry would exhaust memory)
- `audio.encode_wav` and `POST /api/preview`
- `POST /api/songs/{id}/separate` — triggering separation as a job and recording `separation_status` / `separation_reason` from `SeparationResult`
- `/api/renders` — start, cancel, download
- `GET /api/jobs/{id}/events` — SSE progress stream
- `/api/presets` — CRUD over the table Task 2 already creates

Deferred to **Plan 3**: the Elm application, `ports/audio.js`, `ports/events.js`, and replacing the placeholder `index.html`.

Carried forward from Plan 1's ledger, still open:

- `util.iteration_rng` does not validate `seed >= 0`; the natural place for that check is the API boundary this plan introduces, so it becomes actionable in Plan 2b when config arrives over HTTP.
- `session.py`'s cache key covers all of `LoopConfig`, so changing only `crossfade_ms` pays a `find_loop` recompute. Revisit when Plan 3 knows whether a crossfade control exists.
- `docs/architecture.md`'s line citations drifted by one during Plan 1's final fix wave, and the plan addendum still claims a preview has no reverb tail bleed, which is no longer true. Both are corrected as part of Task 7.
