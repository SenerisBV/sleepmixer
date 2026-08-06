# Plan 3c: jobs you can watch and stop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every job in the queue genuinely stoppable, and give the interface a render screen and a queue screen so a finished mix can be produced, watched, cancelled and downloaded without touching the command line.

**Architecture:** Demucs moves into a killable subprocess whose handoff to the parent is the stem cache that already exists; that makes the stem cache write atomic, because a killable writer can now be killed mid-write. On top of that, three Elm screens — renders, queue, and a render button on the mixer — built on API routes that are already implemented and tested.

**Tech Stack:** Python 3.11 / FastAPI / SQLite / numpy / demucs · Elm 0.19.2 · hand-written JS port modules · pytest · elm-test

**Spec:** `docs/superpowers/specs/2026-08-04-render-and-queue-design.md`

## Global Constraints

- **`pipenv` runs only from `/path/to/sleepmixer`. Never `cd` elsewhere first** — pipenv keys its virtualenv to the directory path, and `cd`-ing first silently creates a new empty virtualenv.
- **`elm` and `elm-test` run from `ui/`**, so `cd ui` is correct and necessary for those. These are two different rules; do not conflate them.
- Elm 0.19.2. **No new Elm packages, no npm dependencies, no CSS framework.**
- **No new Python dependencies.** `subprocess`, `threading`, `queue`, `shutil`, `tempfile` are all standard library.
- **No `Debug.toString` or `Debug.log` anywhere under `ui/src`** — `elm make --optimize` refuses to build with them, so `make ui` fails. They are allowed under `ui/tests`.
- **`make ui` from the repository root** rebuilds `sleepmix/static/app.js`, copies the port files and rewrites the hash. Run it and commit whatever it produces; a Python test recomputes the hash and byte-compares the served port files against their sources.
- **Every class emitted from `ui/src` must have a CSS rule in `sleepmix/static/index.html`.** `tests/test_static_bundle.py` enforces this. It reads only `<style>` blocks, strips comments and requires selector position — do not weaken it to make a class pass.
- **No browser automation, AppleScript, screenshots, or browser-driver MCPs.** A prior implementer on this project drove GUI automation against the operator's real desktop and tripped a macOS TCC dialog over a Finder window holding a private key, invoices and a CV. Verify with curl.
- **Every server you start uses `SLEEPMIX_DATA_DIR=$(mktemp -d)`** and is killed afterwards. A prior implementer wrote into the operator's real music library before noticing.
- **Do not run real Demucs separations casually.** They cost minutes. The suite's `stub_separation` fixture and this plan's stub worker exist so that nearly everything can be tested without one.
- Baseline at plan start: **232 Python tests, 180 Elm tests.**

## Notes for whoever executes this

**Tasks 1–5 carry their code and are close to transcription. Tasks 6, 7 and 8 do not** — they describe three screens and give the pure functions and the tests, but not the view markup, which would be several hundred lines of `Html.div` that nobody benefits from reading in a plan. Dispatch those three on a capable model and expect judgment. Task 7's steps are deliberately compressed because it is Task 6's shape applied to a simpler screen; its implementer should read Task 6 first.

**The three riskiest things in this plan, in order:**

1. **Task 2's failure taxonomy.** `separate_detailed` answers "demucs is not installed" by treating the whole song as a single `mix` stem. That is right for that question and silently wrong for every other one — a killed or crashed worker taking that path converts the song to a one-stem mix that then renders and plays without complaining. Three ways of ending, three different answers.
2. **Task 1's atomicity, which Task 2 makes load-bearing.** `_load_cache` returns whatever `.wav` files it finds, so a half-written cache reads back as a smaller, valid separation.
3. **The CSS in Tasks 6–8.** This project has already shipped a feature that rendered as nothing because `index.html` did not grow with the markup. The class-coverage test catches missing rules; it cannot catch a rule scoped to the wrong parent.

---

## File structure

**Server**

| File | Responsibility |
|---|---|
| `sleepmix/separation.py` *(modify)* | Cache read/write, the Demucs call, the unavailable-fallback. Gains an atomic cache write and a `SeparationFailed` exception. |
| `sleepmix/separation_worker.py` *(create)* | The child process. Runs one separation, writes the cache, prints phase lines. Knows nothing about jobs or HTTP. |
| `sleepmix/separation_process.py` *(create)* | The parent-side supervisor. Spawns the worker, forwards phases to a `ProgressReporter`, kills it on cancel, and classifies how it ended. |
| `sleepmix/server/jobs.py` *(modify)* | Token check before a job starts; `created_at`; bounded retention of terminal jobs. |
| `sleepmix/server/api/songs.py` *(modify)* | The separate route calls the supervisor instead of `separate_detailed` directly. |
| `sleepmix/server/api/renders.py` *(modify)* | `DELETE /api/renders/{render_id}`. |

**Frontend**

| File | Responsibility |
|---|---|
| `ui/src/Api.elm` *(modify)* | `Render`, `RenderStatus`, their decoders; `createdAt` on `Job`. |
| `ui/src/Request.elm` *(modify)* | `renders`, `startRender`, `deleteRender`, `jobs`, `cancelJob`. |
| `ui/src/Page/Renders.elm` *(create)* | The renders list: download, audition, delete, progress, cancel. |
| `ui/src/Page/Queue.elm` *(create)* | What is running and what is waiting, with cancel. |
| `ui/src/Warn.elm` *(create)* | One pure function deciding whether a job is long enough to warn about, and the sentence to say. Used by the mixer and the song screen. |
| `ui/src/Main.elm` *(modify)* | Two new routes, their fetches, and the wiring. |
| `ui/src/Page/Mixer.elm` *(modify)* | The render button and its warning. |
| `ui/src/Page/Song.elm` *(modify)* | The separate warning. |
| `sleepmix/static/index.html` *(modify)* | Rules for every class the new views emit. |

---

## Task 1: The stem cache write becomes atomic

**Files:**
- Modify: `sleepmix/separation.py` — `_save_cache`, `_save_fallback_reason`, `separate_detailed`
- Test: `tests/test_separation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_write_cache(cache_dir: str, key: str, stems: dict[str, AudioBuffer], reason: str | None) -> None` — writes the fallback marker and every stem so that they appear together or not at all. `_load_cache` and `_load_fallback_reason` are unchanged.

**Why this is first.** Today nothing can interrupt a cache write. Task 2 makes separation killable, and a directory holding two of four stems reads back through `_load_cache` as a perfectly valid two-stem separation — the song then renders and plays with half its content missing and nothing anywhere saying why. This project has already shipped two bugs of exactly that shape. Do this before the thing that makes it reachable.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_separation.py`:

```python
import os

import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.separation import (
    _cache_key, _load_cache, _load_fallback_reason, _write_cache,
)


def _stems(n: int) -> dict[str, AudioBuffer]:
    return {
        f"stem{i}": AudioBuffer(np.zeros((100, 2), dtype=np.float32), 44100)
        for i in range(n)
    }


def test_a_write_interrupted_partway_leaves_no_cache_at_all(tmp_path, monkeypatch):
    """The failure this exists to prevent: half a separation reading back as a
    whole one. _load_cache returns whatever .wav files it finds, so a directory
    with two of four stems is indistinguishable from a genuine two-stem result."""
    import sleepmix.separation as sep

    calls = {"n": 0}
    real_save = sep.save_audio

    def explode_on_the_third(buf, path):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk went away")
        real_save(buf, path)

    monkeypatch.setattr(sep, "save_audio", explode_on_the_third)

    with pytest.raises(OSError):
        _write_cache(str(tmp_path), "k", _stems(4), None)

    assert _load_cache(str(tmp_path), "k") is None, (
        "a partial write must be invisible, not a smaller valid separation")


def test_an_interrupted_write_does_not_destroy_the_previous_cache(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    _write_cache(str(tmp_path), "k", _stems(4), None)
    before = sorted(_load_cache(str(tmp_path), "k"))

    def always_explode(buf, path):
        raise OSError("disk went away")

    monkeypatch.setattr(sep, "save_audio", always_explode)
    with pytest.raises(OSError):
        _write_cache(str(tmp_path), "k", _stems(2), None)

    assert sorted(_load_cache(str(tmp_path), "k")) == before


def test_the_fallback_marker_lands_with_the_stems(tmp_path):
    _write_cache(str(tmp_path), "k", {"mix": _stems(1)["stem0"]}, "demucs missing")
    assert _load_fallback_reason(str(tmp_path), "k") == "demucs missing"
    assert sorted(_load_cache(str(tmp_path), "k")) == ["mix"]


def test_writing_without_a_reason_clears_a_stale_marker(tmp_path):
    _write_cache(str(tmp_path), "k", _stems(1), "old reason")
    _write_cache(str(tmp_path), "k", _stems(2), None)
    assert _load_fallback_reason(str(tmp_path), "k") is None


def test_no_staging_directories_are_left_behind(tmp_path):
    _write_cache(str(tmp_path), "k", _stems(2), None)
    assert sorted(os.listdir(tmp_path)) == ["k"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_separation.py -k "interrupted or marker or staging" -v`
Expected: FAIL — `cannot import name '_write_cache'`.

- [ ] **Step 3: Implement**

Add `import shutil` and `import tempfile` to `sleepmix/separation.py`, and a new exception near the top:

```python
class SeparationFailed(RuntimeError):
    """The separation did not run to completion for a reason that is not a
    cancellation and not Demucs being unavailable.

    Distinct from the unavailable-fallback on purpose. ``separate_detailed``
    answers "demucs is not installed" with the whole song as a single ``mix``
    stem, which is the right answer to that question and the wrong answer to
    every other one — a crashed or killed worker must not quietly become a
    one-stem mix that then renders and plays without complaining."""
```

Replace `_save_cache` and `_save_fallback_reason` with a single atomic writer:

```python
def _write_cache(cache_dir: str, key: str, stems: dict[str, AudioBuffer],
                 reason: str | None) -> None:
    """Publish a separation: the fallback marker and every stem, together.

    Everything is written into a sibling staging directory and renamed into
    place once it is all on disk, so an interrupted write leaves either the
    previous cache or nothing — never a subset. ``_load_cache`` returns
    whatever ``.wav`` files it finds, so a subset would read back as a smaller
    but perfectly valid separation, and the song would render missing half its
    content with nothing to say so.

    This supersedes an earlier arrangement where the marker was written first
    and the stems second, chosen so that a failure between them left no stems
    and a stale marker (recoverable) rather than fallback stems and no marker
    (which reads as a successful separation). That ordering was the best
    available while the write could not be made atomic. It can be now."""
    final = _cache_path(cache_dir, key)
    os.makedirs(cache_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f".{key}.", dir=cache_dir)
    try:
        if reason is not None:
            with open(os.path.join(staging, _FALLBACK_MARKER), "w") as fh:
                fh.write(reason)
        for name, buf in stems.items():
            save_audio(buf, os.path.join(staging, f"{name}.wav"))
        # rename() onto a non-empty directory fails, so the old one goes first.
        # A crash in this window leaves no cache, which recomputes — the one
        # outcome that is always safe.
        shutil.rmtree(final, ignore_errors=True)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
```

Introduce `_FALLBACK_MARKER` as the bare filename and express `_fallback_marker_path` in terms of it, so the staging copy and the final copy cannot drift:

```python
_FALLBACK_MARKER = "fallback_reason.txt"


def _fallback_marker_path(cache_dir: str, key: str) -> str:
    return os.path.join(_cache_path(cache_dir, key), _FALLBACK_MARKER)
```

(Read the existing `_fallback_marker_path` first and keep its actual filename — the value above is what to use only if it already matches. If it differs, use the existing name; changing it would orphan every cached fallback marker on the operator's disk.)

In `separate_detailed`, replace the two calls with one:

```python
    _write_cache(cache_dir, key, stems, reason)
```

Then grep for any other caller of `_save_cache` or `_save_fallback_reason` and update it. Note that `_load_cache` iterates `.wav` files only, so the marker sitting inside the same directory is already ignored by it.

- [ ] **Step 4: Run the tests**

Run: `pipenv run pytest tests/test_separation.py -v` then `pipenv run pytest -q`
Expected: all pass, 232 + 5 = 237.

- [ ] **Step 5: Commit**

```bash
git add sleepmix/separation.py tests/test_separation.py
git commit -m "fix: publish the stem cache atomically"
```

---

## Task 2: The separation worker, and the supervisor that can kill it

**Files:**
- Create: `sleepmix/separation_worker.py`, `sleepmix/separation_process.py`
- Create: `tests/stub_separation_worker.py`, `tests/test_separation_process.py`

**Interfaces:**
- Consumes: `SeparationFailed`, `separate_detailed`, `_cache_key`, `_load_cache` from Task 1's `sleepmix/separation.py`.
- Produces:
  - `run_separation(input_path: str, model: str, cache_dir: str, reporter: ProgressReporter | None = None, cancel: CancelToken | None = None, worker_module: str = "sleepmix.separation_worker", timeout_s: float = 5.0) -> SeparationResult`
  - The stdout protocol: the child prints `sleepmix-phase <fraction> <message>` lines and nothing else that the parent reads.

**The protocol, stated once.** The child writes one line per phase to stdout:

```
sleepmix-phase 0.05 Loading the model
sleepmix-phase 0.15 Separating stems
sleepmix-phase 0.90 Writing stems
```

`<fraction>` is a float in `[0, 1]`; everything after the second space is the message. The parent ignores every line that does not start with `sleepmix-phase `, because torch and demucs both print warnings to stdout and the supervisor must not choke on them.

Progress inside the separation itself is not available: `_demucs_separate` calls `apply_model(mdl, x[None], progress=False)` and demucs exposes no callback there. Three coarse phases is what there is, and the UI already shows an indeterminate bar for separation, so this is honest rather than a shortfall.

**Why the cache is the handoff.** `separate_detailed` already writes stems to `cache_dir/<key>/<stem>.wav` and reads them back on the next call. So the child runs `separate_detailed` and exits; the parent then calls `separate_detailed` itself and gets a cache hit. No pickling of numpy arrays, no shared memory, no serialisation protocol to keep in step.

**How the child ending is classified.** This is the part to get right.

| How it ended | What the parent does |
|---|---|
| Exit 0, cache present | `separate_detailed` (a cache hit) → `SeparationResult` |
| Exit 0, cache absent | `raise SeparationFailed` — the contract was broken and pretending otherwise would silently produce nothing |
| Killed because we cancelled | `raise Cancelled` |
| Any other non-zero exit | `raise SeparationFailed` with the tail of stderr |

Demucs being unavailable is **not** in this table, because the child handles it: `separate_detailed` catches it, writes the one-stem `mix` fallback and its marker, and exits 0. That keeps the fallback attached to the one question it answers.

- [ ] **Step 1: Write the stub worker**

`tests/stub_separation_worker.py` — a stand-in for the real child, so cancel, phase forwarding and failure can be tested in milliseconds instead of minutes:

```python
"""A separation worker that does no separation.

Everything about supervising a child process — forwarding its phases, killing
it on cancel, telling a crash from a cancellation — is independent of what the
child computes. Testing that against real Demucs would mean minutes per case
and a machine with torch on it. This stub takes the same argv as the real
worker and is told, through the environment, how to misbehave:

    STUB_SLEEP_S     seconds to sleep after printing its phases (default 0)
    STUB_EXIT_CODE   exit with this code instead of 0
    STUB_NO_CACHE    exit 0 without writing any cache
    STUB_STDOUT_NOISE print an unparseable line first, as torch does
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.separation import _cache_key, _write_cache


def main(argv: list[str]) -> int:
    input_path, model, cache_dir = argv[1], argv[2], argv[3]
    if os.environ.get("STUB_STDOUT_NOISE"):
        print("some torch warning nobody asked for", flush=True)
    print("sleepmix-phase 0.05 Loading the model", flush=True)
    print("sleepmix-phase 0.15 Separating stems", flush=True)
    time.sleep(float(os.environ.get("STUB_SLEEP_S", "0")))
    code = int(os.environ.get("STUB_EXIT_CODE", "0"))
    if code:
        print("stub failing on purpose", file=sys.stderr, flush=True)
        return code
    if not os.environ.get("STUB_NO_CACHE"):
        stems = {
            name: AudioBuffer(np.zeros((100, 2), dtype=np.float32), 44100)
            for name in ("vocals", "drums", "bass", "other")
        }
        _write_cache(cache_dir, _cache_key(input_path, model), stems, None)
    print("sleepmix-phase 0.90 Writing stems", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 2: Write the failing tests**

`tests/test_separation_process.py`:

```python
import os
import time

import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.progress import CancelToken, Cancelled, ProgressReporter
from sleepmix.separation import SeparationFailed, _cache_key, _write_cache
from sleepmix.separation_process import run_separation

STUB = "tests.stub_separation_worker"


@pytest.fixture
def song(tmp_path):
    path = tmp_path / "song.wav"
    save_audio(AudioBuffer(np.zeros((44100, 2), dtype=np.float32), 44100), str(path))
    return str(path)


def _collect(events):
    return ProgressReporter(lambda e: events.append((e.fraction, e.message)))


def test_a_cache_hit_never_spawns_anything(song, tmp_path, monkeypatch):
    """The warm path must stay warm. Spawning a process to discover we already
    had the answer would put a torch import in front of every separated song."""
    stems = {"vocals": AudioBuffer(np.zeros((10, 2), dtype=np.float32), 44100)}
    _write_cache(str(tmp_path), _cache_key(song, "m"), stems, None)

    def forbidden(*a, **k):
        raise AssertionError("spawned a worker for a cache hit")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    result = run_separation(song, "m", str(tmp_path), worker_module=STUB)
    assert sorted(result.stems) == ["vocals"]


def test_phases_reach_the_reporter(song, tmp_path):
    events = []
    result = run_separation(song, "m", str(tmp_path),
                            reporter=_collect(events), worker_module=STUB)
    assert sorted(result.stems) == ["bass", "drums", "other", "vocals"]
    assert [m for _, m in events][:2] == ["Loading the model", "Separating stems"]


def test_unparseable_output_is_ignored(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_STDOUT_NOISE", "1")
    events = []
    run_separation(song, "m", str(tmp_path), reporter=_collect(events),
                   worker_module=STUB)
    assert all(m for _, m in events), "a noise line became an empty phase"


def test_cancelling_kills_the_child_and_raises(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    token = CancelToken()
    import threading
    threading.Timer(0.4, token.cancel).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)
    elapsed = time.monotonic() - started
    assert elapsed < 10, f"took {elapsed:.1f}s — the child was not killed"


def test_a_cancel_that_lands_before_the_spawn_still_raises(song, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        run_separation(song, "m", str(tmp_path), cancel=token, worker_module=STUB)


def test_a_nonzero_exit_is_a_failure_not_a_fallback(song, tmp_path, monkeypatch):
    """The distinction that matters: a crashed worker must not become a
    one-stem 'mix', which would render and play without complaining."""
    monkeypatch.setenv("STUB_EXIT_CODE", "3")
    with pytest.raises(SeparationFailed) as exc:
        run_separation(song, "m", str(tmp_path), worker_module=STUB)
    assert "3" in str(exc.value)
    assert "stub failing on purpose" in str(exc.value)


def test_exiting_cleanly_without_writing_a_cache_is_a_failure(song, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_NO_CACHE", "1")
    with pytest.raises(SeparationFailed):
        run_separation(song, "m", str(tmp_path), worker_module=STUB)
```

- [ ] **Step 3: Run to verify they fail**

Run: `pipenv run pytest tests/test_separation_process.py -v`
Expected: FAIL — `No module named 'sleepmix.separation_process'`.

- [ ] **Step 4: Write the worker**

`sleepmix/separation_worker.py`:

```python
"""One separation, in its own process, so it can be killed.

Demucs is a single opaque call — ``apply_model`` returns when it returns, and
no cancel token gets a look in. Before this existed, cancelling a running
separation set a flag nobody would read until the work was already done, which
meant a large file blocked everything behind it until the server was killed by
hand.

The handoff to the parent is the stem cache, which already existed: this writes
it, the parent reads it. No arrays cross the process boundary.

Run as ``python -m sleepmix.separation_worker <input> <model> <cache_dir>``.
"""
from __future__ import annotations

import sys

from .separation import separate_detailed


def _phase(fraction: float, message: str) -> None:
    # Flushed per line: the parent reads these as they arrive, and a buffered
    # phase is a progress bar that stalls for the length of the separation.
    print(f"sleepmix-phase {fraction} {message}", flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: python -m sleepmix.separation_worker "
              "<input> <model> <cache_dir>", file=sys.stderr)
        return 2
    input_path, model, cache_dir = argv[1], argv[2], argv[3]
    _phase(0.05, "Loading the model")
    _phase(0.15, "Separating stems")
    # Demucs-unavailable is handled in here, writing the one-stem 'mix'
    # fallback and its marker, and exiting 0. That keeps the fallback attached
    # to the one question it answers; every other way of ending is a failure
    # the parent must not paper over.
    separate_detailed(input_path, model, cache_dir)
    _phase(0.90, "Writing stems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 5: Write the supervisor**

`sleepmix/separation_process.py`:

```python
"""Run a separation in a child process and be able to stop it.

The parent's whole job is to forward the child's phases, kill it when asked,
and be exact about how it ended — because the three ways it can end need three
different answers and two of them are silent if confused. A cancelled
separation must leave the song exactly as it was; a crashed one must say so;
and only "demucs is not installed", which the child handles itself, may fall
back to treating the whole song as a single stem.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading

from .progress import CancelToken, Cancelled, ProgressReporter
from .separation import (
    SeparationFailed, SeparationResult, _cache_key, _load_cache,
    separate_detailed,
)

_PHASE_PREFIX = "sleepmix-phase "
_POLL_S = 0.1


def _pump(stream, sink: queue.Queue) -> None:
    for line in stream:
        sink.put(line.rstrip("\n"))
    sink.put(None)


def run_separation(
    input_path: str,
    model: str,
    cache_dir: str,
    reporter: ProgressReporter | None = None,
    cancel: CancelToken | None = None,
    worker_module: str = "sleepmix.separation_worker",
    timeout_s: float = 5.0,
) -> SeparationResult:
    key = _cache_key(input_path, model)
    if _load_cache(cache_dir, key) is not None:
        # Warm path: no process, no torch import. Roughly every separated song
        # the operator reopens takes this branch.
        return separate_detailed(input_path, model, cache_dir)

    if cancel is not None:
        cancel.check()

    os.makedirs(cache_dir, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", worker_module, input_path, model, cache_dir],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    lines: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    reader.start()

    # stderr is drained on its own thread rather than read at the end. torch and
    # demucs both write warnings there, and an undrained pipe fills its buffer
    # and blocks the child forever — a separation that hangs instead of
    # finishing, with no error anywhere. Collected into a list so the tail is
    # available for the failure message.
    errs: list[str] = []
    draining = threading.Thread(
        target=lambda: errs.extend(proc.stderr), daemon=True)
    draining.start()

    cancelled = False
    while True:
        if cancel is not None and cancel.cancelled and not cancelled:
            # terminate() first so the child can die tidily; kill() only if it
            # will not. A torch process that ignores SIGTERM is not a reason to
            # keep the operator waiting.
            cancelled = True
            proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            line = lines.get(timeout=_POLL_S)
        except queue.Empty:
            if proc.poll() is not None and lines.empty():
                break
            continue
        if line is None:
            break
        if reporter is not None and line.startswith(_PHASE_PREFIX):
            rest = line[len(_PHASE_PREFIX):]
            fraction, _, message = rest.partition(" ")
            try:
                reporter.emit("separate", message, float(fraction))
            except ValueError:
                pass

    proc.wait()
    reader.join(timeout=timeout_s)
    draining.join(timeout=timeout_s)
    stderr = "".join(errs).strip()

    if cancelled or (cancel is not None and cancel.cancelled):
        raise Cancelled()
    if proc.returncode != 0:
        raise SeparationFailed(
            f"separation worker exited {proc.returncode}: {stderr[-2000:]}")
    if _load_cache(cache_dir, key) is None:
        raise SeparationFailed(
            "separation worker exited cleanly but wrote no stems"
            + (f": {stderr[-2000:]}" if stderr else ""))
    return separate_detailed(input_path, model, cache_dir)
```

- [ ] **Step 6: Run the tests**

Run: `pipenv run pytest tests/test_separation_process.py -v` then `pipenv run pytest -q`
Expected: all pass. The cancel test should finish in about a second, not thirty.

- [ ] **Step 7: Prove the stub is not the only thing being tested**

The tests above prove the supervisor works against a stub. They do not prove the real worker speaks the same protocol. Add one slow test, marked so it can be skipped:

```python
@pytest.mark.slow
def test_the_real_worker_speaks_the_same_protocol(song, tmp_path):
    """Without this, every test above proves only that the stub works.

    Runs the real worker on one second of silence. If demucs is not installed
    it takes the unavailable-fallback inside the child and still exits 0 with a
    cache — which is the contract being checked here, not the stem quality."""
    events = []
    result = run_separation(song, "htdemucs_ft", str(tmp_path),
                            reporter=_collect(events))
    assert result.stems
    assert any(m == "Loading the model" for _, m in events)
```

Register the marker in `pytest.ini`/`pyproject.toml` alongside any existing markers, and run it once explicitly:

Run: `pipenv run pytest tests/test_separation_process.py -m slow -v`
Expected: PASS. Note in the report how long it took.

- [ ] **Step 8: Commit**

```bash
git add sleepmix/separation_worker.py sleepmix/separation_process.py \
        tests/stub_separation_worker.py tests/test_separation_process.py
git commit -m "feat: run separation in a killable subprocess"
```

---

## Task 3: The separate route uses the supervisor

**Files:**
- Modify: `sleepmix/server/api/songs.py:129-158` — the `work` closure inside `separate_song`
- Test: `tests/test_api_songs.py`

**Interfaces:**
- Consumes: `run_separation(...)` from Task 2.
- Produces: no new API surface. `POST /api/songs/{id}/separate` behaves as before except that a cancel now stops it.

**What changes in `work`.** It currently calls `separate_detailed(path, model, cache_dir=str(cache_dir()))` directly, with a single `cancel.check()` before it — the check that made cancellation useless, because after it Demucs runs to completion no matter what. Replace that call with `run_separation(...)`, passing the reporter and the token straight through.

Keep every existing branch. `except Cancelled` still resets the row to `pending` with no reason, because nothing was produced and the honest state is the one we started from — "failed" would imply the song is broken. `except Exception` still records `failed` with the type and message, and `SeparationFailed` lands there naturally, which is the point of it being an ordinary exception rather than a special case.

Keep the pre-spawn `cancel.check()` and the comment explaining why it sits before `invalidate_cache` rather than after: a cancel landing in that window would otherwise delete the cached stems on its way out and leave the song with nothing, having been asked to stop.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_songs.py`:

```python
def test_cancelling_a_separation_leaves_the_song_pending(client, tmp_path, monkeypatch):
    """Cancel used to return success and change nothing — the job ran to the
    end and the operator had to kill the server. The row must come back to
    where it started, not to 'failed': nothing was produced and nothing is
    broken."""
    monkeypatch.setenv("STUB_SLEEP_S", "30")
    monkeypatch.setattr(
        "sleepmix.server.api.songs.run_separation",
        lambda *a, **k: __import__(
            "sleepmix.separation_process", fromlist=["run_separation"]
        ).run_separation(*a, **k, worker_module="tests.stub_separation_worker"))

    song = client.post("/api/songs", json={"path": str(_a_wav(tmp_path))}).json()
    started = client.post(f"/api/songs/{song['id']}/separate")
    assert started.status_code == 202
    job_id = started.json()["job"]["id"]

    assert client.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True
    _wait_for_terminal(client, job_id)

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
    assert client.get(f"/api/songs/{song['id']}").json()["separation_status"] == "pending"
```

Write `_a_wav(tmp_path)` and `_wait_for_terminal(client, job_id)` as module-level helpers if the file does not already have equivalents — check first and reuse. `_wait_for_terminal` polls `GET /api/jobs/{id}` until the status is one of `done`, `failed`, `cancelled`, with a hard deadline of 15 seconds and an explicit failure message naming the last status seen, so a hang reads as a diagnosis rather than a timeout.

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_api_songs.py -k cancelling -v`
Expected: FAIL — either the import of `run_separation` does not exist yet, or the job never reaches `cancelled`.

- [ ] **Step 3: Implement**

In `sleepmix/server/api/songs.py`, import the supervisor and use it:

```python
from ...separation_process import run_separation
```

and inside `work`:

```python
            result = run_separation(path, model, str(cache_dir()),
                                    reporter=reporter, cancel=cancel)
```

Leave `separate_detailed`'s import if anything else in the module uses it; remove it if nothing does.

- [ ] **Step 4: Run the tests**

Run: `pipenv run pytest tests/test_api_songs.py -v` then `pipenv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleepmix/server/api/songs.py tests/test_api_songs.py
git commit -m "feat: a running separation can now be cancelled"
```

---

## Task 4: Job manager hardening, and deleting a render

**Files:**
- Modify: `sleepmix/server/jobs.py` — `Job`, `submit`, `_run`, a new `_evict`
- Modify: `sleepmix/server/api/renders.py` — a new `DELETE /{render_id}`
- Modify: `sleepmix/server/store.py` — a new `delete_render`
- Test: `tests/test_jobs.py`, `tests/test_api_renders.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Job.created_at: str` — ISO-8601, in `as_event()` as `created_at`
  - `JobManager(..., keep_terminal: int = 50)`
  - `Store.delete_render(render_id: str) -> bool`
  - `DELETE /api/renders/{render_id}` → 204, or 404, or 409 while its job is still running

**Three separate problems, one task because each is a few lines and a reviewer would accept or reject them together.**

**(a) `_run` starts a job it was told to cancel.** It sets `running` and calls the work function without consulting the token. Cancelling a job still sitting in the pool queue therefore does not stop it starting — it starts, then stops at its first `cancel.check()`, which for separation is the check before Demucs. The visible effect is a cancelled job that runs anyway.

**(b) `_jobs` only ever grows.** Nothing is removed for the life of the process, so `GET /api/jobs` returns every job since startup and the queue screen would render all of it. Keep the most recent 50 terminal jobs and drop older ones. **Never drop a `queued` or `running` job**, however many there are — dropping one would make the queue lie about what is about to happen, which is the one thing the screen exists not to do.

**(c) Renders accumulate on disk.** A half-hour WAV is around 300 MB and nothing deletes one.

- [ ] **Step 1: Write the failing tests**

`tests/test_jobs.py`:

```python
def test_a_job_cancelled_before_it_starts_never_runs():
    """It used to run anyway: _run flipped the status to 'running' and called
    the work function without ever looking at the token."""
    manager = JobManager(max_workers=1)
    ran = []
    gate = threading.Event()

    def blocker(reporter, cancel):
        gate.wait(timeout=5)
        return {}

    def second(reporter, cancel):
        ran.append(True)
        return {}

    first = manager.submit("test", blocker)
    queued = manager.submit("test", second)
    assert manager.cancel(queued.id) is True
    gate.set()
    _wait_for(lambda: manager.get(queued.id).status in TERMINAL_STATUSES)

    assert ran == [], "the work function ran for a job that was cancelled"
    assert manager.get(queued.id).status == "cancelled"
    manager.shutdown(wait=True)


def test_terminal_jobs_are_evicted_but_live_ones_never_are():
    manager = JobManager(max_workers=1, keep_terminal=3)
    done = [manager.submit("test", lambda r, c: {}) for _ in range(6)]
    for job in done:
        _wait_for(lambda job=job: manager.get(job.id).status in TERMINAL_STATUSES)

    remaining = [j.id for j in manager.list()]
    assert len(remaining) == 3
    assert remaining == [j.id for j in done[-3:]], "evicted the newest, not the oldest"
    manager.shutdown(wait=True)


def test_a_job_carries_when_it_was_created():
    manager = JobManager(max_workers=1)
    job = manager.submit("test", lambda r, c: {})
    assert job.as_event()["created_at"]
    manager.shutdown(wait=True)
```

`_wait_for(predicate)` polls at 20 ms with a 5-second deadline and asserts with a message naming what it was waiting for. Write it once at module level.

`tests/test_api_renders.py`:

```python
def test_deleting_a_render_removes_the_row_and_the_file(client, tmp_path):
    render = _a_finished_render(client, tmp_path)
    path = render["path"]
    assert os.path.isfile(path)

    assert client.delete(f"/api/renders/{render['id']}").status_code == 204
    assert client.get(f"/api/renders/{render['id']}").status_code == 404
    assert not os.path.exists(path)


def test_deleting_an_unknown_render_is_a_404(client):
    assert client.delete("/api/renders/nope").status_code == 404


def test_a_render_that_is_still_running_cannot_be_deleted(client, tmp_path):
    """Deleting the file out from under a running pipeline would leave the job
    writing to a path nobody will look at, and the row it would update gone."""
    render = _a_running_render(client, tmp_path)
    response = client.delete(f"/api/renders/{render['id']}")
    assert response.status_code == 409
    assert "cancel" in response.json()["detail"].lower()
```

`tests/test_store.py`:

```python
def test_delete_render_reports_whether_there_was_one(store):
    render = store.add_render(song_id="s", config={}, path="/tmp/x.wav", status="done")
    assert store.delete_render(render["id"]) is True
    assert store.get_render(render["id"]) is None
    assert store.delete_render(render["id"]) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_jobs.py tests/test_api_renders.py tests/test_store.py -v`
Expected: FAIL on the new names and on `_run` starting a cancelled job.

- [ ] **Step 3: Implement the job manager changes**

In `sleepmix/server/jobs.py`, add `from datetime import datetime, timezone` and give `Job` a timestamp:

```python
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
    created_at: str = ""
```

Set it in `submit`, and take the retention bound in `__init__`:

```python
    def __init__(self, loop=None, max_workers: int = 1,
                 keep_terminal: int = 50) -> None:
        ...
        self._keep_terminal = keep_terminal
```

```python
    def submit(self, kind: str, fn: JobFn, song_id: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, song_id=song_id,
                  created_at=datetime.now(timezone.utc).isoformat())
        ...
```

Guard the start:

```python
    def _run(self, job_id: str, fn: JobFn, token: CancelToken) -> None:
        if token.cancelled:
            # Cancelled while it was still sitting in the pool's queue. Without
            # this it would start anyway and only stop at the work function's
            # first check() — which for separation is the check that happens
            # before Demucs, so the cancel was invisible.
            self._update(job_id, status="cancelled", message="Cancelled")
            return
        self._update(job_id, status="running")
        ...
```

Evict at the end of `_update` when a job has just become terminal:

```python
    def _evict(self) -> None:
        """Drop the oldest terminal jobs, keeping queued and running ones.

        Called with the lock held. ``_jobs`` is insertion-ordered, and a job's
        position never changes, so the oldest terminal job is the first one in
        iteration order — no sorting needed. Live jobs are never dropped
        however many there are: the queue screen's whole purpose is to say what
        is about to happen, and a dropped queued job makes it lie."""
        terminal = [jid for jid, j in self._jobs.items()
                    if j.status in TERMINAL_STATUSES]
        for jid in terminal[:max(0, len(terminal) - self._keep_terminal)]:
            self._jobs.pop(jid, None)
            self._tokens.pop(jid, None)
            self._subscribers.pop(jid, None)
```

Call `self._evict()` inside `_update` while the lock is held, only when the new status is terminal. **Do not evict a job whose subscribers list is non-empty without dropping it from `_subscribers` too** — the code above does both, which matters because `stream_job` holds a queue reference and an eviction that left `_subscribers` behind would leak.

- [ ] **Step 4: Implement the store and route**

`sleepmix/server/store.py`, beside the other render methods:

```python
    def delete_render(self, render_id: str) -> bool:
        """True if there was a row to delete. The file is the caller's problem;
        this object owns the database and nothing else."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM renders WHERE id = ?", (render_id,))
            return cur.rowcount > 0
```

`sleepmix/server/api/renders.py`:

```python
@router.delete("/{render_id}", status_code=204)
def delete_render(render_id: str, request: Request) -> Response:
    """Remove a render and its file.

    Refused while the render is still being produced: the pipeline would go on
    writing to a path nobody will look at, and the row it updates on completion
    would be gone. Cancel the job first — that path already deletes the partial
    file through ``_abandon``."""
    store = request.app.state.store
    render = store.get_render(render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="No such render")
    if render["status"] in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail="This render is still being produced — cancel it first.")
    path = render["path"]
    store.delete_render(render_id)
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        # The row is gone, which is what the caller asked for. A file we cannot
        # remove is a disk problem, not a reason to resurrect the record.
        pass
    return Response(status_code=204)
```

Import `Response` from `fastapi` at the top of the file.

- [ ] **Step 5: Run the tests**

Run: `pipenv run pytest tests/test_jobs.py tests/test_api_renders.py tests/test_store.py -v` then `pipenv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add sleepmix/server/jobs.py sleepmix/server/store.py \
        sleepmix/server/api/renders.py tests/
git commit -m "feat: honour cancel before a job starts, bound job retention, delete renders"
```

---

## Task 5: The Elm data layer for renders and jobs

**Files:**
- Modify: `ui/src/Api.elm`, `ui/src/Request.elm`
- Test: `ui/tests/ApiTest.elm` (or the existing decoder test module — check which exists and extend it)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```elm
type RenderStatus
    = RenderQueued
    | RenderRunning
    | RenderDone
    | RenderFailed
    | RenderCancelled


type alias Render =
    { id : String
    , songId : String
    , status : RenderStatus
    , path : String
    , durationMin : Maybe Float
    , config : Decode.Value
    , createdAt : String
    }


render : Decoder Render
renderStatusLabel : RenderStatus -> String
isRenderFinished : RenderStatus -> Bool
```

and on `Request`:

```elm
renders : (Result Http.Error (List Api.Render) -> msg) -> Cmd msg
startRender : String -> Encode.Value -> (Result Http.Error Api.Job -> msg) -> Cmd msg
deleteRender : String -> (Result Http.Error () -> msg) -> Cmd msg
jobs : (Result Http.Error (List Api.Job) -> msg) -> Cmd msg
cancelJob : String -> (Result Http.Error Api.Job -> msg) -> Cmd msg
```

`Api.Job` also gains `createdAt : String`.

**Decode against the server's real output, not an imagined shape.** Before writing the decoder, start a server on a throwaway data dir and look at what the routes actually return:

```bash
SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open --port 8765 &
curl -s localhost:8765/api/renders
curl -s localhost:8765/api/jobs
```

In particular, establish whether `config` comes back as a JSON object or as a string of JSON, and whether `duration_min` is `null` before a render finishes. Paste the real fragments into the tests as string literals. This is the same discipline that made `Schema.elm` correct on the first try, and the reason is the same: a decoder built against a guess fails at runtime in the browser, where nobody in this loop can see it.

**Keep the union closed.** Follow `Api.SeparationStatus` and `Api.JobStatus`: `andThen` over an exhaustive `case` with `other -> Decode.fail`, and no catch-all success branch. A render status this application cannot render must fail loudly rather than display as something plausible.

- [ ] **Step 1: Write the failing tests**

In the Elm decoder test module, using the fragments captured above as string literals, cover: a `queued` render with `duration_min: null` decodes with `durationMin = Nothing`; a `done` render decodes with a `Just`; every one of the five statuses maps to its intended variant; an unknown status **fails** the decode; and a job now carries `createdAt`. Write the unknown-status test with `Expect.err`, not by asserting some fallback value.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && elm-test`
Expected: FAIL to compile — `Api.Render` does not exist.

- [ ] **Step 3: Implement**

Add the types and decoder to `ui/src/Api.elm` following the shape of `Api.song` and `Api.job` — `Pipeline.required` / `Pipeline.optional` as those do. Add `createdAt` to `Job` and its decoder.

Add the five request functions to `ui/src/Request.elm` following the shape of the ones already there (`Http.get` / `Http.post` with `Url.Builder.absolute`). `deleteRender` uses `Http.request` with `method = "DELETE"` and `Http.expectWhatever`, because the route answers 204 with no body and `expectJson` would fail on it.

- [ ] **Step 4: Run the tests and rebuild**

Run: `cd ui && elm-test`, then from the repository root `make ui && pipenv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/Api.elm ui/src/Request.elm ui/tests sleepmix/static
git commit -m "feat: decode renders and jobs"
```

---

## Task 6: The renders screen

**Files:**
- Create: `ui/src/Page/Renders.elm`, `ui/tests/RendersTest.elm`
- Modify: `ui/src/Main.elm` (route, fetch, wiring), `sleepmix/static/index.html` (CSS)

**Interfaces:**
- Consumes: `Api.Render`, `Api.RenderStatus`, `Request.renders`, `Request.deleteRender`, `Request.cancelJob` from Task 5.
- Produces: `Page.Renders.view : Config msg -> Html msg`, where `Config` carries the renders, the songs (to resolve titles), the job currently being watched, and the message constructors for delete, cancel and back.

**The screen.** One row per render, newest first:

- The song's title, resolved by joining `render.songId` against the songs the model already holds. A render whose song has since been removed shows the id rather than blank.
- **A config summary: the mix length, which stems were enabled, and the decay endpoint.** Those are the three things that differ between two renders of the same song in practice, and without them a list of six identically-titled entries is useless. The row expands to show the stored config in full.
- **Done** — a download link, an audition, and delete.
- **Running or queued** — the progress bar and a cancel button.
- **Failed or cancelled** — the reason, and delete.

**The audition is a plain `<audio controls>` element** pointed at `/api/renders/{id}/audio`. Not the Web Audio port: that port decodes a whole buffer into memory to loop it, which is right for a short preview and wrong for half an hour of WAV — roughly 300 MB decoded. An `<audio>` element streams it, costs nothing, and needs no JavaScript at all. Render it with `Html.audio [ Attr.controls True, Attr.src (...) ] []`.

**Testing.** The view is markup; the logic worth testing is the joining and the summarising. `ui/tests/RendersTest.elm` covers: a render whose song is present shows its title; a render whose song is absent shows the id and does not crash; the config summary of two renders of the same song with different stem sets differs; `durationMin = Nothing` renders as something other than "0 minutes". Test those as pure functions — extract `titleFor`, `summarise` and anything else with a decision in it out of the view so `elm-test` can reach them, exactly as `Preview.elm` was extracted from the audio port for the same reason.

- [ ] **Step 1: Write the failing tests**

Write `ui/tests/RendersTest.elm` against the four behaviours above. Give each test a name that states the behaviour, not the function — `a render whose song has been removed shows its id rather than nothing`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ui && elm-test`
Expected: FAIL to compile — `Page.Renders` does not exist.

- [ ] **Step 3: Implement `Page/Renders.elm`**

Structure it as `Page/Song.elm` and `Page/Mixer.elm` are structured: a `Config msg` record of everything the page needs plus the message constructors, a `view` taking it, and the pure helpers the tests call exposed by name.

- [ ] **Step 4: Wire it into `Main.elm`**

Add `RendersView` to the `Route` union. Follow the existing convention: routes are **derived** from the model rather than stored, so add whatever field genuinely represents "the renders screen is open" and extend `routeFor`. Fetch `Request.renders` on entering the screen and after any delete or cancel.

Reuse the existing SSE machinery for a running render — `watchJob` / `jobEvent` / `stopWatchingJob` already exist and the separation panel already drives them. Do not add a second mechanism.

- [ ] **Step 5: Write the CSS**

Add a rule for every class the new view emits, in `sleepmix/static/index.html`, matching the existing dark, quiet style. **Then verify it, because this is the failure this project has already shipped:** on an earlier branch the SSE progress bar rendered as nothing because `index.html` never grew as the markup did.

Run: `pipenv run pytest tests/test_static_bundle.py -v`
Expected: PASS, including the class-coverage test.

Then check something the test cannot: that every class has a rule proves nothing about whether the rule applies *where* the class is emitted. `.back` was styled under `.song-view` and emitted under `.mixer` for exactly this reason. Read your selectors against your markup.

- [ ] **Step 6: Run everything, rebuild, commit**

```bash
cd ui && elm-test
cd /path/to/sleepmixer && make ui && pipenv run pytest -q
git add ui sleepmix/static && git commit -m "feat: the renders screen"
```

---

## Task 7: The queue screen

**Files:**
- Create: `ui/src/Page/Queue.elm`, `ui/tests/QueueTest.elm`
- Modify: `ui/src/Main.elm`, `sleepmix/static/index.html`

**Interfaces:**
- Consumes: `Api.Job`, `Request.jobs`, `Request.cancelJob` from Task 5.
- Produces: `Page.Queue.view : Config msg -> Html msg`, and the pure helpers its tests reach.

**The screen.** Everything currently in flight, in submission order — `created_at` ascending — with the kind of job, the song it belongs to, its status and progress, and a cancel button on every entry. Running first, then queued, then the recent terminal ones.

**It says that it is live-only.** `JobManager` is in memory and resets on every server start, so after a restart this screen is empty and that is correct rather than broken. Say so on the screen, briefly. A screen that goes blank for a structural reason and does not explain itself is the same class of problem as a progress bar with no bar.

**Refresh.** A job the user is not watching still needs to move. Poll `Request.jobs` on a timer while this screen is open — `Time.every` with a several-second interval — and stop when it closes. Do not open an SSE stream per job: `events.js` is built around watching one job, the manager fans out per subscriber, and a screen with ten entries would open ten streams. Polling a list is the right shape for a list.

**Testing.** Ordering and grouping are the logic: `ui/tests/QueueTest.elm` covers that running jobs sort before queued ones, that queued jobs are in `created_at` order rather than arrival-of-response order, that a terminal job is not shown as cancellable, and that an empty list produces the explanatory line rather than nothing. Extract the ordering as a pure function and test that.

- [ ] **Step 1: Write the failing tests** — the four behaviours above, in `ui/tests/QueueTest.elm`.
- [ ] **Step 2: Run to verify they fail.** `cd ui && elm-test`, expect a compile failure on `Page.Queue`.
- [ ] **Step 3: Implement `Page/Queue.elm`**, same shape as `Page/Renders.elm`.
- [ ] **Step 4: Wire into `Main.elm`** — the route, the poll subscription while open, and cancel re-fetching the list.
- [ ] **Step 5: CSS for every emitted class**, then `pipenv run pytest tests/test_static_bundle.py -v`, then read your selectors against your markup as in Task 6 Step 5.
- [ ] **Step 6: Run everything, rebuild, commit**

```bash
cd ui && elm-test
cd /path/to/sleepmixer && make ui && pipenv run pytest -q
git add ui sleepmix/static && git commit -m "feat: the queue screen"
```

---

## Task 8: Starting a render, and the long-job warnings

**Files:**
- Create: `ui/src/Warn.elm`, `ui/tests/WarnTest.elm`
- Modify: `ui/src/Page/Mixer.elm`, `ui/src/Page/Song.elm`, `ui/src/Main.elm`, `sleepmix/static/index.html`

**Interfaces:**
- Consumes: `Request.startRender` from Task 5; `Config.encode` from `ui/src/Config.elm`, which is what the mixer already sends with every preview.
- Produces:

```elm
module Warn exposing (Warning(..), forSource)


type Warning
    = NoWarning
    | Long String


{-| Whether a job on this much source audio is worth warning about.
-}
forSource : Float -> Warning
```

**The render button lives on the mixer**, because that is where the config lives. It sends `Request.startRender songId (Config.encode model.config)` — the same encoder the previews use, so what you render is what you have been listening to — and then moves to the renders screen, where the job is already visible.

**It says what it is about to do before it does it:** the mix length from `output.duration_min`, and whether the stems are already cached — the single biggest factor in how long this takes.

**It does not fabricate a time estimate.** We have no model of render duration, and a bar that lies about time left is precisely what this project has avoided elsewhere — the "Preparing…" panel is deliberately indeterminate for the same reason. Task 9 measures a real render and records the ratio; only then, and only if it proves stable across two tracks, may an estimate become something the interface claims.

**The warning threshold is 15 minutes of source audio.** Roughly three times the longest track anyone would normally feed this; the file that caused the original incident was seventy. It exists to catch the accident, not to editorialise about long songs. `Warn.forSource` takes `durationS` and returns the sentence, which must say both the source length and that one worker runs everything, so anything started behind it waits. It warns; it does not block.

Both the mixer's Render button and the song screen's Separate button use it. It is one module rather than two copies because the two screens must not drift into saying different things about the same constraint.

- [ ] **Step 1: Write the failing test**

`ui/tests/WarnTest.elm`:

```elm
suite : Test
suite =
    describe "Warn.forSource"
        [ test "an ordinary track says nothing" <|
            \_ -> Expect.equal Warn.NoWarning (Warn.forSource 245)
        , test "a track just under the threshold says nothing" <|
            \_ -> Expect.equal Warn.NoWarning (Warn.forSource 899)
        , test "a track over the threshold warns" <|
            \_ ->
                case Warn.forSource 4188 of
                    Warn.Long message ->
                        Expect.all
                            [ \m -> Expect.equal True (String.contains "69" m || String.contains "70" m)
                            , \m -> Expect.equal True (String.contains "one" m || String.contains "1 " m)
                            ]
                            message

                    Warn.NoWarning ->
                        Expect.fail "a 70-minute file must warn"
        ]
```

The 4188-second case is the actual file that caused the original incident.

- [ ] **Step 2: Run to verify it fails.** `cd ui && elm-test`, expect a compile failure on `Warn`.
- [ ] **Step 3: Implement `Warn.elm`.**
- [ ] **Step 4: Add the render button to `Page/Mixer.elm`** with its pre-flight line and the warning, and the `Separate`-side warning to `Page/Song.elm`. Wire `Request.startRender` and its response through `Main.elm`, moving to the renders screen on success.
- [ ] **Step 5: CSS for every emitted class**, then `pipenv run pytest tests/test_static_bundle.py -v`, then read the selectors against the markup.
- [ ] **Step 6: Run everything, rebuild, commit**

```bash
cd ui && elm-test
cd /path/to/sleepmixer && make ui && pipenv run pytest -q
git add ui sleepmix/static && git commit -m "feat: start a render from the mixer, and warn before long jobs"
```

---

## Task 9: Verification, and the documentation

**Files:**
- Modify: `docs/architecture.md`, `docs/project-state.md`, `README.md`, `ui/README.md`

**Write no application code in this task.** If verification uncovers a bug, report it prominently and leave it; the whole-branch review is next.

- [ ] **Step 1: Verify the whole path, against a throwaway data dir**

```bash
SLEEPMIX_DATA_DIR=$(mktemp -d) pipenv run sleepmix ui --no-open --port 8765
```

Import a song, separate it, **cancel the separation partway and confirm the song comes back to `pending` with its previous cache intact**, separate it again to completion, start a render, watch `GET /api/jobs/{id}/events` to `done`, download the audio and confirm it is a RIFF/WAVE file of roughly the configured length, then delete it and confirm both the row and the file are gone.

Then the one that matters most: **start a render and cancel it midway.** Confirm the job reaches `cancelled`, the render row reads `cancelled`, and no partial file is left in the renders directory.

**Measure one full render end to end** and record the source length, the mix length, and the wall-clock time. That number is what a future estimate would have to be built on, and right now nobody has it.

Kill the server. **No browser automation.**

- [ ] **Step 2: Update the docs**

`docs/architecture.md`: why separation runs in a subprocess and what the cache handoff is; the phase protocol; how the three ways a child can end map to three different outcomes, and why conflating them would be silent. Add the measured render timing beside the existing preview timings, stated with its track length as those are.

`docs/project-state.md`: remove the gaps this plan closes — no render screen, no queue visibility, no warning before a large import, and no way to stop a running separation. Record what remains: presets and per-song memory (Plan 3d), no persistence of the job queue across restarts, and the torch-import cost now paid per separation.

`README.md` and `ui/README.md`: describe what the interface does now, at their existing level of detail.

**Check every claim against the source.** A confident sentence about behaviour that does not exist is worse than no sentence.

- [ ] **Step 3: Commit**

```bash
git add docs README.md ui/README.md
git commit -m "docs: the render and queue screens, and killable separation"
```

---

## What this plan does not cover

**Plan 3d:** the presets UI — named recipes reusable across songs, on the presets table and routes that already exist — and per-song config memory, so reopening a song restores what you left.

**Not planned:** persisting the job queue across restarts; fine-grained separation progress, which demucs does not expose at the point that matters; segment selection and arrangement, whose seam is `LoopConfig.start_s`/`end_s` plus the loop endpoint but which breaks the one-loop-repeated model in `pipeline.py` and needs its own design; a path allow-list for `import_song`; streaming peak computation; authentication.
