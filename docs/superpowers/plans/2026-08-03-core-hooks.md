# sleepmix Core Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the core capabilities a UI needs — window-level preview, memoized render sessions, structured progress with cancellation, config field metadata, relocated cache paths, and per-iteration RNG — without changing CLI behavior.

**Architecture:** All work is additive to the existing `sleepmix/` package. The decay engine already exposes a pure function of progress (`apply_decay`), so preview is a matter of extracting the per-iteration plan into shared helpers that both the batch stream builder and a new preview path call. No server or frontend code in this plan.

**Tech Stack:** Python ≥3.10, numpy, scipy, pytest. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-sleepmix-ui-design.md`

## Global Constraints

- Python ≥3.10 (`requires-python` in `pyproject.toml`). No 3.11+ syntax.
- **No new required runtime dependencies.** New core code uses numpy/scipy/stdlib only.
- **The CLI must not regress.** `sleepmix render` terminal output stays byte-identical to today's. Any progress refactor adapts back to `click.echo` strings.
- Every optional dependency stays optional. Never import `librosa`, `demucs`, `torch`, `pedalboard`, or `pyrubberband` at module scope.
- Audio is always float32, shape `(n_frames, n_channels)`.
- Existing public API — `MixConfig`, `run_pipeline` — keeps working. Renders will not be byte-identical to pre-existing output (accepted: per-iteration RNG, Task 3).
- Follow existing file conventions: module docstring explaining *why*, `from __future__ import annotations`, private helpers prefixed `_`.

---

### Task 1: Dev tooling and green baseline

Establishes that the suite runs before anything changes behavior. `pytest` is currently absent from the pipenv environment (`[dev-packages]` in the Pipfile is empty), so no test can be written or run until this lands.

**Files:**
- Modify: `Pipfile` (`[dev-packages]` section)

- [ ] **Step 1: Add pytest to dev-packages**

In `Pipfile`, replace the empty `[dev-packages]` section with:

```toml
[dev-packages]
pytest = ">=7.4"
```

- [ ] **Step 2: Install it**

Run: `pipenv install --dev`
Expected: pytest resolves and installs; `Pipfile.lock` updates.

- [ ] **Step 3: Run the existing suite to establish the baseline**

Run: `pipenv run pytest -q`
Expected: PASS. All existing tests in `tests/` green.

If anything fails here, stop and report — the baseline must be green before Task 3 changes render output.

- [ ] **Step 4: Commit**

```bash
git add Pipfile Pipfile.lock
git commit -m "chore: add pytest to dev-packages"
```

---

### Task 2: `paths.py` — app data and cache locations

`separation.py:25` defaults `cache_dir` to the CWD-relative `.sleepmix_cache`, and `pipeline.py:36` never passes it through — so cache location silently depends on the launch directory.

**Files:**
- Create: `sleepmix/paths.py`
- Modify: `sleepmix/pipeline.py` (the `separate` call)
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `data_dir() -> pathlib.Path` — app data root, created on call
  - `cache_dir() -> pathlib.Path` — separation cache, created on call
  - Both honor the `SLEEPMIX_DATA_DIR` environment variable

- [ ] **Step 1: Write the failing test**

Create `tests/test_paths.py`:

```python
from pathlib import Path

from sleepmix import paths


def test_data_dir_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "custom"))
    assert paths.data_dir() == tmp_path / "custom"


def test_data_dir_is_created(tmp_path, monkeypatch):
    target = tmp_path / "made" / "here"
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(target))
    assert paths.data_dir().is_dir()


def test_cache_dir_lives_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert paths.cache_dir().parent == tmp_path
    assert paths.cache_dir().is_dir()


def test_platform_data_dir_is_absolute_and_not_cwd():
    """Assert on the default location without creating it.

    ``_platform_data_dir`` is a pure resolver — it does no I/O — so this checks
    the default is a real per-user path without writing anything into the
    operator's actual home. Calling ``data_dir()`` here instead would create
    that directory for real, which the suite must never do.
    """
    d = paths._platform_data_dir()
    assert d.is_absolute()
    assert d != Path.cwd()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_paths.py -v`
Expected: FAIL — `ImportError: cannot import name 'paths' from 'sleepmix'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/paths.py`:

```python
"""Where sleepmix keeps its data.

The separation cache used to be a CWD-relative ``.sleepmix_cache``, which meant
its location depended on where you happened to launch from — fine for a CLI you
run from the project directory, wrong for a long-lived server process. These
helpers resolve to a stable per-user location instead, overridable with
``SLEEPMIX_DATA_DIR`` (which the test suite uses to stay off real data).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_VAR = "SLEEPMIX_DATA_DIR"


def data_dir() -> Path:
    """Application data root. Created if missing."""
    override = os.environ.get(ENV_VAR)
    d = Path(override).expanduser() if override else _platform_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    """Stem-separation cache. Created if missing."""
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _platform_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sleepmix"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "sleepmix"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sleepmix"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pipenv run pytest tests/test_paths.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire it into the pipeline**

In `sleepmix/pipeline.py`, add to the imports:

```python
from .paths import cache_dir
```

Then change the `separate` call (currently `pipeline.py:36`) from:

```python
    stems = separate(input_path, config.separation_model)
```

to:

```python
    stems = separate(input_path, config.separation_model, cache_dir=str(cache_dir()))
```

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS. Note that `tests/test_pipeline.py` will now write its cache to the real data dir — Task 2 Step 7 fixes that.

- [ ] **Step 7: Isolate the test suite from real data**

Create `tests/conftest.py`:

```python
"""Keep the whole test suite off the operator's real data directory.

``autouse`` means every test gets an isolated SLEEPMIX_DATA_DIR whether it asks
for one or not — the separation cache and (later) the library database must
never touch real files during a test run.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "sleepmix-data"))
    yield
```

- [ ] **Step 8: Run the full suite again**

Run: `pipenv run pytest -q`
Expected: PASS, and no new directory created under `~/Library/Application Support/sleepmix` (macOS) during the run.

- [ ] **Step 9: Commit**

```bash
git add sleepmix/paths.py sleepmix/pipeline.py tests/test_paths.py tests/conftest.py
git commit -m "feat: stable app-data and cache paths, isolated from CWD"
```

---

### Task 3: Per-iteration RNG

Currently one `rng` is threaded through the whole pipeline (`pipeline.py:33`), so the noise, dropout, and spectral-hole pattern at iteration *i* depends on every draw before it — which makes it impossible for a preview of a single point in the arc to match the real render. This task makes each iteration's randomness a pure function of `(seed, stem, iteration)`.

**This is the accepted behavior change**: existing renders will not reproduce byte-for-byte.

**Files:**
- Modify: `sleepmix/util.py` (add `iteration_rng`)
- Modify: `sleepmix/disintegration.py` (add `plan_iterations`, `decayed_iteration`; rewrite `build_disintegrating_stream`)
- Modify: `sleepmix/pipeline.py:81-82` (call site)
- Test: `tests/test_disintegration.py` (update two tests, add three)

**Interfaces:**
- Consumes: `apply_decay(loop, progress, decay, rng) -> AudioBuffer` (unchanged)
- Produces:
  - `util.iteration_rng(seed: int, stem: str, iteration: int) -> np.random.Generator`
  - `disintegration.plan_iterations(loop_frames: int, target_frames: int, crossfade_ms: float, sr: int) -> tuple[int, int]` returning `(n_iterations, xfade_frames)`
  - `disintegration.decayed_iteration(loop: AudioBuffer, iteration: int, n_iterations: int, decay: StemDecayConfig, seed: int, stem: str) -> AudioBuffer`
  - `disintegration.build_disintegrating_stream(loop, target_frames, decay, crossfade_ms, seed: int, stem: str = "mix") -> AudioBuffer` — **signature change**: final `rng` parameter replaced by `seed` + `stem`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_disintegration.py` (keep the existing imports and helpers; extend the import line):

```python
from sleepmix.disintegration import (
    apply_decay, build_disintegrating_stream, decayed_iteration, plan_iterations)
from sleepmix.util import iteration_rng
```

Then add these tests:

```python
def test_iteration_rng_is_reproducible():
    a = iteration_rng(7, "vocals", 3).standard_normal(8)
    b = iteration_rng(7, "vocals", 3).standard_normal(8)
    assert np.array_equal(a, b)


def test_iteration_rng_differs_across_iteration_stem_and_seed():
    base = iteration_rng(7, "vocals", 3).standard_normal(8)
    assert not np.array_equal(base, iteration_rng(7, "vocals", 4).standard_normal(8))
    assert not np.array_equal(base, iteration_rng(7, "bass", 3).standard_normal(8))
    assert not np.array_equal(base, iteration_rng(8, "vocals", 3).standard_normal(8))


def test_stream_iteration_matches_decayed_iteration():
    """The stream is genuinely built from decayed_iteration outputs.

    Iteration i occupies out[i*stride : i*stride + loop_len]. Its neighbours
    overlap only in the crossfade regions, so [i*stride + xfade, (i+1)*stride]
    is contributed by iteration i alone and must match exactly.
    """
    loop = _tone(440, secs=0.5)
    decay = StemDecayConfig()
    target = loop.sr * 3
    xfade_ms = 50.0

    stream = build_disintegrating_stream(
        loop, target, decay, xfade_ms, seed=11, stem="vocals")
    n_iter, xfade = plan_iterations(loop.n_frames, target, xfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)

    i = 1
    chunk = decayed_iteration(loop, i, n_iter, decay, seed=11, stem="vocals")
    lo = i * stride + xfade
    hi = min((i + 1) * stride, target)
    assert hi > lo, "test setup produced no clean region"
    assert np.allclose(stream.data[lo:hi], chunk.data[xfade:xfade + (hi - lo)], atol=1e-6)
```

Update the two existing tests that pass an `rng` to `build_disintegrating_stream`:

```python
def test_stream_hits_target_length():
    loop = _tone(440, secs=0.5)
    target = loop.sr * 3  # 3 seconds from a 0.5s loop
    stream = build_disintegrating_stream(
        loop, target, StemDecayConfig(), crossfade_ms=50, seed=0, stem="mix")
    assert stream.n_frames == target
    assert np.all(np.isfinite(stream.data))


def test_stream_is_deterministic_with_seed():
    loop = _tone(440, secs=0.5)
    target = loop.sr * 2
    a = build_disintegrating_stream(loop, target, StemDecayConfig(), 50, seed=42, stem="mix")
    b = build_disintegrating_stream(loop, target, StemDecayConfig(), 50, seed=42, stem="mix")
    assert np.array_equal(a.data, b.data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_disintegration.py -v`
Expected: FAIL — `ImportError: cannot import name 'decayed_iteration'`

- [ ] **Step 3: Add `iteration_rng` to `util.py`**

Add to the top of `sleepmix/util.py`:

```python
import hashlib
```

And append:

```python
def iteration_rng(seed: int, stem: str, iteration: int) -> np.random.Generator:
    """A generator determined solely by ``(seed, stem, iteration)``.

    Deriving randomness per iteration rather than drawing from one shared stream
    is what lets a preview of a single point in the decay arc reproduce exactly
    what the full render produces there. With a shared generator, iteration i's
    noise depends on every draw before it, so nothing can be previewed in
    isolation."""
    h = int.from_bytes(hashlib.sha256(stem.encode("utf-8")).digest()[:8], "big")
    return np.random.default_rng([int(seed), h, int(iteration)])
```

- [ ] **Step 4: Add the iteration helpers to `disintegration.py`**

Add to the imports in `sleepmix/disintegration.py`:

```python
from .util import db_to_amp, iteration_rng, lerp, shape_progress
```

Then add these two functions above `build_disintegrating_stream`:

```python
def plan_iterations(
    loop_frames: int, target_frames: int, crossfade_ms: float, sr: int
) -> tuple[int, int]:
    """Return ``(n_iterations, xfade_frames)`` for a stream of this shape.

    Shared by the batch stream builder and the preview path so both agree on
    which iteration a given point in the arc corresponds to."""
    xfade = min(int(crossfade_ms / 1000.0 * sr), loop_frames // 2)
    stride = max(loop_frames - xfade, 1)
    n_iter = int(np.ceil((target_frames - xfade) / stride)) + 1
    return max(n_iter, 1), xfade


def decayed_iteration(
    loop: AudioBuffer,
    iteration: int,
    n_iterations: int,
    decay: StemDecayConfig,
    seed: int,
    stem: str,
) -> AudioBuffer:
    """The loop as it sounds on repetition ``iteration`` of ``n_iterations``."""
    progress = iteration / max(n_iterations - 1, 1)
    return apply_decay(loop, progress, decay, iteration_rng(seed, stem, iteration))
```

- [ ] **Step 5: Rewrite `build_disintegrating_stream` to use them**

Replace the whole of `build_disintegrating_stream` in `sleepmix/disintegration.py` with:

```python
def build_disintegrating_stream(
    loop: AudioBuffer,
    target_frames: int,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
) -> AudioBuffer:
    """Repeat ``loop`` until ``target_frames`` is reached, degrading each pass.

    Successive iterations are joined with an equal-power crossfade so cycle
    boundaries don't click. Each iteration's randomness is derived from
    ``(seed, stem, iteration)`` so any single iteration can be reproduced in
    isolation — see ``util.iteration_rng``."""
    sr = loop.sr
    ch = loop.n_channels
    loop_len = loop.n_frames
    n_iter, xfade = plan_iterations(loop_len, target_frames, crossfade_ms, sr)

    out = np.zeros((target_frames + loop_len, ch), dtype=np.float32)
    pos = 0
    for i in range(n_iter):
        chunk = decayed_iteration(loop, i, n_iter, decay, seed, stem).data
        if pos == 0:
            out[:loop_len] += chunk
            pos = loop_len
        else:
            start = pos - xfade
            a = out[start:start + xfade]
            b = chunk[:xfade]
            out[start:start + xfade] = equal_power_crossfade(a, b)
            end = start + loop_len
            out[start + xfade:end] += chunk[xfade:]
            pos = end
        if pos >= target_frames:
            break

    return AudioBuffer(out[:target_frames], sr)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_disintegration.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Update the pipeline call site**

In `sleepmix/pipeline.py`, `_process_stem` currently calls (at `pipeline.py:81-82`):

```python
    stream = build_disintegrating_stream(
        loop, target_frames, sc.decay, config.output.cycle_crossfade_ms, rng)
```

Change to:

```python
    stream = build_disintegrating_stream(
        loop, target_frames, sc.decay, config.output.cycle_crossfade_ms,
        config.seed, sc.name)
```

`_process_stem` no longer needs its `rng` parameter. Remove it from the signature and from the call in `run_pipeline`. The `rng` created at `pipeline.py:33` is still needed for `build_soundbed`, so leave that line alone.

- [ ] **Step 8: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add sleepmix/util.py sleepmix/disintegration.py sleepmix/pipeline.py tests/test_disintegration.py
git commit -m "feat: derive decay randomness per iteration

Each iteration's noise, dropouts and spectral holes are now a pure function
of (seed, stem, iteration) rather than draws from one shared generator. This
is what makes it possible to preview a single point in the decay arc and get
exactly what the full render produces there.

Renders will not reproduce byte-for-byte against previous output."
```

---

### Task 4: `progress.py` — structured events and cancellation

**Files:**
- Create: `sleepmix/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ProgressEvent` dataclass with fields `stage: str`, `stem: str | None`, `fraction: float`, `message: str`
  - `ProgressReporter(sink: Callable[[ProgressEvent], None] | None)` with `.emit(stage, message, fraction, stem=None)` and `.stage_range(lo, hi)` context manager
  - `CancelToken` with `.cancel()`, `.cancelled` property, `.check()` raising `Cancelled`
  - `Cancelled(Exception)`
  - `echo_sink(echo: Callable[[str], None]) -> Callable[[ProgressEvent], None]` — adapts events back to plain strings for the CLI

- [ ] **Step 1: Write the failing test**

Create `tests/test_progress.py`:

```python
import pytest

from sleepmix.progress import (
    CancelToken, Cancelled, ProgressEvent, ProgressReporter, echo_sink)


def test_reporter_emits_events_to_sink():
    seen = []
    r = ProgressReporter(seen.append)
    r.emit("separate", "Separating stems…", 0.0)
    r.emit("master", "Mastering…", 1.0)
    assert [e.stage for e in seen] == ["separate", "master"]
    assert seen[0].message == "Separating stems…"


def test_fraction_is_clamped_and_monotonic():
    seen = []
    r = ProgressReporter(seen.append)
    r.emit("a", "x", 0.5)
    r.emit("b", "y", 0.2)      # regression is clamped up to the previous value
    r.emit("c", "z", 5.0)      # over-range is clamped down to 1.0
    fractions = [e.fraction for e in seen]
    assert fractions == [0.5, 0.5, 1.0]


def test_stage_range_maps_local_progress_into_a_slice():
    seen = []
    r = ProgressReporter(seen.append)
    with r.stage_range(0.4, 0.8):
        r.emit("stem", "half way through this stage", 0.5)
    assert seen[0].fraction == pytest.approx(0.6)


def test_reporter_with_no_sink_is_a_noop():
    r = ProgressReporter(None)
    r.emit("a", "x", 0.5)      # must not raise


def test_cancel_token_starts_uncancelled():
    t = CancelToken()
    assert not t.cancelled
    t.check()                  # must not raise


def test_cancel_token_raises_after_cancel():
    t = CancelToken()
    t.cancel()
    assert t.cancelled
    with pytest.raises(Cancelled):
        t.check()


def test_echo_sink_renders_events_as_strings():
    lines = []
    sink = echo_sink(lines.append)
    sink(ProgressEvent(stage="separate", stem=None, fraction=0.0,
                       message="Separating stems…"))
    assert lines == ["Separating stems…"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.progress'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/progress.py`:

```python
"""Structured progress reporting and cooperative cancellation.

The pipeline used to take a bare ``Callable[[str], None]`` and print sentences
at it. That is enough for a terminal but not for a UI, which needs to know
*which* stage is running and how far along the whole render is. Events carry
both; the CLI adapts them back to plain strings via ``echo_sink`` so its output
is unchanged.

Cancellation is cooperative: long loops call ``CancelToken.check()`` at points
where abandoning the work is safe.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator


class Cancelled(Exception):
    """Raised by ``CancelToken.check`` once cancellation has been requested."""


@dataclass(frozen=True)
class ProgressEvent:
    stage: str            # separate | loop | stem | soundbed | master
    stem: str | None
    fraction: float       # 0..1 across the whole render
    message: str


Sink = Callable[[ProgressEvent], None]


class CancelToken:
    """A flag the caller can raise and long-running work polls."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def check(self) -> None:
        if self._cancelled:
            raise Cancelled("render cancelled")


class ProgressReporter:
    """Emits :class:`ProgressEvent` to a sink, keeping ``fraction`` sane.

    ``fraction`` is clamped to [0, 1] and never allowed to go backwards, since a
    progress bar that retreats is worse than one that stalls."""

    def __init__(self, sink: Sink | None = None) -> None:
        self._sink = sink
        self._last = 0.0
        self._lo = 0.0
        self._hi = 1.0

    def emit(self, stage: str, message: str, fraction: float,
             stem: str | None = None) -> None:
        local = min(max(float(fraction), 0.0), 1.0)
        overall = self._lo + (self._hi - self._lo) * local
        overall = min(max(overall, self._last), 1.0)
        self._last = overall
        if self._sink is not None:
            self._sink(ProgressEvent(stage=stage, stem=stem,
                                     fraction=overall, message=message))

    @contextmanager
    def stage_range(self, lo: float, hi: float) -> Iterator["ProgressReporter"]:
        """Scope emissions to the ``[lo, hi]`` slice of overall progress.

        Inside the block, ``emit(..., 0.5)`` means "half way through this
        stage", not "half way through the render"."""
        prev = (self._lo, self._hi)
        self._lo, self._hi = lo, hi
        try:
            yield self
        finally:
            self._lo, self._hi = prev


def echo_sink(echo: Callable[[str], None]) -> Sink:
    """Adapt events back to the plain strings the CLI has always printed."""
    def sink(event: ProgressEvent) -> None:
        echo(event.message)
    return sink
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pipenv run pytest tests/test_progress.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add sleepmix/progress.py tests/test_progress.py
git commit -m "feat: structured progress events and cancellation token"
```

---

### Task 5: Wire progress and cancellation into the pipeline

**Files:**
- Modify: `sleepmix/pipeline.py` (signature, all `progress(...)` calls, stem loop)
- Modify: `sleepmix/disintegration.py` (`build_disintegrating_stream` gains an optional cancel check)
- Modify: `sleepmix/cli.py:41` (adapt events to `click.echo`)
- Modify: `tests/conftest.py` (add `fake_separate` and the `stub_separation` fixture)
- Test: `tests/test_pipeline.py` (add three tests)

**Interfaces:**
- Consumes: `ProgressReporter`, `CancelToken`, `Cancelled`, `echo_sink` from Task 4
- Produces:
  - `run_pipeline(input_path, config, output_path, progress=print, reporter=None, cancel=None) -> AudioBuffer`
    - `progress` keeps its old meaning (a string callback) for backward compatibility
    - `reporter: ProgressReporter | None` takes precedence when given
    - `cancel: CancelToken | None` aborts with `Cancelled`
  - `conftest.fake_separate(input_path, model=..., cache_dir=None) -> dict[str, AudioBuffer]` — four deterministic synthetic stems
  - `stub_separation` fixture, returning `fake_separate`; used by Tasks 5, 8 and 9

- [ ] **Step 1: Write the separation stub**

Real separation takes ~10 s per call (measured, Demucs on a 6 s file) and the
cache misses on every fresh `tmp_path`, so tests that render would spend minutes
exercising the ML model rather than the code under test.

The stub lives in `tests/conftest.py` rather than its own module so tests can
reach it through a fixture — `tests/` is not a package, so a sibling module
would need import gymnastics.

Append to `tests/conftest.py`:

```python
import numpy as np

from sleepmix.audio import AudioBuffer, load_audio

STUB_STEM_NAMES = ("vocals", "drums", "bass", "other")


def fake_separate(input_path, model="htdemucs_ft", cache_dir=None):
    """A stand-in for Demucs.

    Real separation takes about ten seconds per call and the on-disk cache keys
    on file path, size and mtime — so every test using a fresh ``tmp_path`` song
    would miss the cache and run the model for real. These stems are synthetic,
    deterministic, and distinct from each other so solo/sum behaviour is
    observable."""
    src = load_audio(str(input_path))
    t = np.arange(src.n_frames) / src.sr
    stems = {}
    for i, name in enumerate(STUB_STEM_NAMES):
        y = (0.2 * np.sin(2 * np.pi * 110 * (i + 1) * t)).astype(np.float32)
        stems[name] = AudioBuffer(np.stack([y, y], axis=1), src.sr)
    return stems


@pytest.fixture
def stub_separation(monkeypatch):
    """Replace Demucs wherever the pipeline reaches for it.

    ``sleepmix/pipeline.py`` does ``from .separation import separate``, so the
    name must be patched on the *pipeline* module, not on ``sleepmix.separation``.
    Returns the stub so tests can also inject it directly (``RenderSession``
    takes a ``separate_fn``)."""
    import sleepmix.pipeline

    monkeypatch.setattr(sleepmix.pipeline, "separate", fake_separate)
    return fake_separate
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_pipeline.py` (extend the imports):

```python
import pytest

from sleepmix.progress import CancelToken, Cancelled, ProgressReporter
```

Then add:

```python
def test_reporter_receives_ordered_monotonic_events(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    seen = []
    run_pipeline(str(song), cfg, str(out), reporter=ProgressReporter(seen.append))

    stages = [e.stage for e in seen]
    assert stages[0] == "separate"
    assert stages[-1] == "master"
    assert "stem" in stages
    fractions = [e.fraction for e in seen]
    assert fractions == sorted(fractions), "progress must never go backwards"
    assert 0.0 <= fractions[0] and fractions[-1] <= 1.0


def test_cancel_aborts_the_render(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    token = CancelToken()
    # Cancel as soon as the first event arrives.
    reporter = ProgressReporter(lambda _e: token.cancel())

    with pytest.raises(Cancelled):
        run_pipeline(str(song), cfg, str(out), reporter=reporter, cancel=token)

    assert not out.exists(), "a cancelled render must not leave output behind"


def test_string_progress_callback_still_works(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    lines = []
    run_pipeline(str(song), cfg, str(out), progress=lines.append)

    assert any("Separating" in line for line in lines)
    assert any("Wrote" in line for line in lines)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `TypeError: run_pipeline() got an unexpected keyword argument 'reporter'`

- [ ] **Step 4: Add a cancel check to the stream builder**

In `sleepmix/disintegration.py`, add the optional parameter to `build_disintegrating_stream`:

```python
def build_disintegrating_stream(
    loop: AudioBuffer,
    target_frames: int,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
```

And inside the `for i in range(n_iter):` loop, as the first line of the body:

```python
        if cancel is not None:
            cancel.check()
```

Keep the rest of the function exactly as Task 3 left it. The parameter is untyped-by-import on purpose so `disintegration.py` doesn't import `progress`; any object with a `.check()` method works.

- [ ] **Step 5: Rewrite the pipeline's progress handling**

In `sleepmix/pipeline.py`, replace the imports and `run_pipeline` signature. Add:

```python
from .progress import CancelToken, ProgressReporter
```

Change `run_pipeline` to:

```python
def run_pipeline(
    input_path: str,
    config: MixConfig,
    output_path: str,
    progress: Progress = print,
    reporter: ProgressReporter | None = None,
    cancel: CancelToken | None = None,
) -> AudioBuffer:
    """Render ``input_path`` to ``output_path``.

    ``reporter`` supersedes ``progress`` when given; ``progress`` remains for
    callers that just want printed sentences."""
    if reporter is None:
        reporter = ProgressReporter(
            lambda e: progress(e.message) if progress else None)
    rng = np.random.default_rng(config.seed)

    reporter.emit("separate", "Separating stems…", 0.0)
    stems = separate(input_path, config.separation_model, cache_dir=str(cache_dir()))
    work_sr = next(iter(stems.values())).sr
    if cancel is not None:
        cancel.check()

    reporter.emit("loop", "Finding loop points…", 0.10)
    reference = _sum_buffers(list(stems.values()))
    loop_point = find_loop(reference, config.loop)
    reporter.emit("loop",
                  f"  tempo≈{loop_point.tempo:.0f} BPM, "
                  f"loop={(loop_point.end-loop_point.start)/work_sr:.1f}s", 0.15)

    target_frames = int(config.output.duration_min * 60 * work_sr)
    jobs = _plan_jobs(stems, config)

    mix = silence(target_frames, config.output.channels, work_sr)
    # Stems occupy the 0.15–0.85 slice of overall progress.
    for idx, (buf, sc) in enumerate(jobs):
        lo = 0.15 + 0.70 * (idx / len(jobs))
        hi = 0.15 + 0.70 * ((idx + 1) / len(jobs))
        with reporter.stage_range(lo, hi):
            reporter.emit("stem", f"Processing stem '{sc.name}'…", 0.0, stem=sc.name)
            stream = _process_stem(buf, sc, loop_point, config, target_frames, cancel)
            mix = _add(mix, stream)

    if config.soundbed.enabled:
        reporter.emit("soundbed", "Adding sound bed…", 0.88)
        bed = build_soundbed(target_frames / work_sr, work_sr, config.soundbed, rng)
        mix = _add(mix, bed.with_channels(config.output.channels))

    if cancel is not None:
        cancel.check()
    reporter.emit("master", "Mastering…", 0.92)
    if mix.sr != config.output.sample_rate:
        mix = resample(mix, config.output.sample_rate)
    mix = _apply_fades(mix, config.output.fade_in_s, config.output.fade_out_s)
    mix = normalize_peak(mix, config.output.peak_db)

    save_audio(mix, output_path)
    reporter.emit("master", f"Wrote {output_path} ({mix.duration/60:.1f} min)", 1.0)
    return mix
```

Update `_process_stem` to take and forward `cancel` instead of `rng`:

```python
def _process_stem(
    buf: AudioBuffer,
    sc: StemConfig,
    loop_point,
    config: MixConfig,
    target_frames: int,
    cancel=None,
) -> AudioBuffer:
    loop = slice_loop(buf, loop_point)
    loop = make_seamless(loop, config.loop.crossfade_ms)
    loop = slow_and_pitch(loop, config.tempo.speed, config.tempo.pitch_semitones)
    stream = build_disintegrating_stream(
        loop, target_frames, sc.decay, config.output.cycle_crossfade_ms,
        config.seed, sc.name, cancel=cancel)
    stream = apply_reverb(stream, config.reverb, wet_scale=sc.reverb_send)
    if abs(sc.gain_db) > 1e-6:
        stream = AudioBuffer(stream.data * db_to_amp(sc.gain_db), stream.sr)
    return stream.with_channels(config.output.channels)
```

- [ ] **Step 6: Update the CLI to use the reporter**

In `sleepmix/cli.py`, add to the imports:

```python
from .progress import ProgressReporter, echo_sink
```

And change the final line of the `render` command (currently `cli.py:41`) from:

```python
    run_pipeline(input_path, cfg, output_path, progress=click.echo)
```

to:

```python
    run_pipeline(input_path, cfg, output_path,
                 reporter=ProgressReporter(echo_sink(click.echo)))
```

- [ ] **Step 7: Run the tests**

Run: `pipenv run pytest tests/test_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Verify the CLI output is unchanged by hand**

Run:

```bash
pipenv run python -c "
import numpy as np, tempfile, os
from sleepmix.audio import AudioBuffer, save_audio
sr=22050; t=np.arange(int(sr*6))/sr
y=sum(np.sin(2*np.pi*f*t) for f in (220,277,330))/4
d=tempfile.mkdtemp(); p=os.path.join(d,'s.wav')
save_audio(AudioBuffer(np.stack([y,y],axis=1).astype(np.float32),sr),p)
print(p)
" | tail -1 | xargs -I{} pipenv run sleepmix render --input {} --duration 0.1 --output /tmp/cli-check.wav
```

Expected output — five lines, exactly as before:

```
Separating stems…
Finding loop points…
  tempo≈… BPM, loop=…s
Processing stem '…'…
Mastering…
Wrote /tmp/cli-check.wav (0.1 min)
```

- [ ] **Step 9: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add sleepmix/pipeline.py sleepmix/disintegration.py sleepmix/cli.py tests/test_pipeline.py
git commit -m "feat: structured progress and cancellation through the pipeline"
```

---

### Task 6: Config field metadata and schema export

A UI that hard-codes its controls drifts from the config. Exposing bounds, units and labels as dataclass field metadata means a new config field shows up in the UI automatically.

**Files:**
- Modify: `sleepmix/config.py` (metadata on fields, add `config_schema()`)
- Test: `tests/test_config.py` (add four tests)

**Interfaces:**
- Consumes: nothing
- Produces: `config.config_schema() -> dict` — nested description of every config field: `{"fields": {name: {"type", "default", "label", "help", "min", "max", "step", "unit", "choices"}}, "sections": {name: <same shape>}}`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
from sleepmix.config import MixConfig, config_schema


def test_schema_describes_tempo_speed():
    s = config_schema()
    speed = s["sections"]["tempo"]["fields"]["speed"]
    assert speed["type"] == "float"
    assert speed["default"] == 0.7
    assert speed["min"] == 0.05
    assert speed["max"] == 1.0
    assert speed["label"]


def test_schema_exposes_curve_choices():
    s = config_schema()
    curve = s["sections"]["stem_decay"]["fields"]["curve"]
    assert set(curve["choices"]) == {"linear", "exp", "log"}


def test_schema_includes_units_where_meaningful():
    s = config_schema()
    assert s["sections"]["output"]["fields"]["duration_min"]["unit"] == "min"
    assert s["sections"]["stem_decay"]["fields"]["lowpass_end_hz"]["unit"] == "Hz"


def test_metadata_does_not_change_defaults_or_yaml_loading(tmp_path):
    # Defaults survive the addition of metadata.
    assert MixConfig().tempo.speed == 0.7
    assert MixConfig().output.duration_min == 20.0
    # Partial YAML still merges as before.
    p = tmp_path / "c.yaml"
    p.write_text("tempo:\n  speed: 0.5\n")
    cfg = MixConfig.from_yaml(str(p))
    assert cfg.tempo.speed == 0.5
    assert cfg.tempo.pitch_semitones == -2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'config_schema'`

- [ ] **Step 3: Add metadata to config fields**

In `sleepmix/config.py`, annotate fields with `field(default=..., metadata=...)`. Apply this to every field. The full set for two representative dataclasses — follow the same pattern for `LoopConfig`, `ReverbConfig`, `SoundbedConfig`, `StemConfig`:

```python
@dataclass
class TempoConfig:
    speed: float = field(default=0.7, metadata={
        "label": "Speed", "unit": "×", "min": 0.05, "max": 1.0, "step": 0.01,
        "help": "Playback speed as a fraction of the original. 0.7 = 70% speed."})
    pitch_semitones: float = field(default=-2.0, metadata={
        "label": "Pitch", "unit": "st", "min": -12.0, "max": 12.0, "step": 0.5,
        "help": "Semitones to shift, independent of speed."})


@dataclass
class OutputConfig:
    duration_min: float = field(default=20.0, metadata={
        "label": "Duration", "unit": "min", "min": 1.0, "max": 480.0, "step": 1.0,
        "help": "Length of the finished mix."})
    sample_rate: int = field(default=44100, metadata={
        "label": "Sample rate", "unit": "Hz", "choices": [22050, 44100, 48000]})
    channels: int = field(default=2, metadata={
        "label": "Channels", "choices": [1, 2]})
    cycle_crossfade_ms: float = field(default=800.0, metadata={
        "label": "Cycle crossfade", "unit": "ms", "min": 0.0, "max": 5000.0,
        "step": 10.0, "help": "Crossfade between successive loop cycles."})
    fade_in_s: float = field(default=8.0, metadata={
        "label": "Fade in", "unit": "s", "min": 0.0, "max": 120.0, "step": 1.0})
    fade_out_s: float = field(default=12.0, metadata={
        "label": "Fade out", "unit": "s", "min": 0.0, "max": 120.0, "step": 1.0})
    peak_db: float = field(default=-1.0, metadata={
        "label": "Peak ceiling", "unit": "dBFS", "min": -12.0, "max": 0.0,
        "step": 0.1})
```

For `StemDecayConfig`, the `curve` field carries the choices the schema test looks for:

```python
    curve: str = field(default="linear", metadata={
        "label": "Curve", "choices": ["linear", "exp", "log"],
        "help": "linear · exp (ease-in, dissolves late) · log (ease-out, "
                "degrades fast then lingers)"})
    lowpass_start_hz: float = field(default=18000.0, metadata={
        "label": "Lowpass start", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0})
    lowpass_end_hz: float = field(default=1600.0, metadata={
        "label": "Lowpass end", "unit": "Hz", "min": 20.0, "max": 20000.0,
        "step": 100.0})
```

Apply the same treatment to the remaining `StemDecayConfig` fields (`amp_start_db`/`amp_end_db` in dB from -60 to 0; `dropout_start`/`dropout_end` unitless 0–1 step 0.01; `noise_start_db`/`noise_end_db` in dB from -120 to 0; `spectral_hole_start`/`spectral_hole_end` unitless 0–1 step 0.01) and to `enabled` (`{"label": "Enabled"}`).

**Do not change any default value.** Metadata is inert to dataclass construction — `_build` and YAML loading are unaffected.

- [ ] **Step 4: Add `config_schema`**

Append to `sleepmix/config.py`:

```python
# -- schema export ------------------------------------------------------
_SECTION_TYPES = {
    "loop": LoopConfig,
    "tempo": TempoConfig,
    "reverb": ReverbConfig,
    "soundbed": SoundbedConfig,
    "output": OutputConfig,
    "stem": StemConfig,
    "stem_decay": StemDecayConfig,
}


def config_schema() -> dict[str, Any]:
    """Describe every config field so a UI can generate its own controls.

    Hard-coding controls in the frontend means they drift from the config the
    moment a parameter is added. This is the single source of truth for bounds,
    units and labels."""
    return {
        "fields": _describe_fields(MixConfig),
        "sections": {name: {"fields": _describe_fields(t)}
                     for name, t in _SECTION_TYPES.items()},
    }


def _describe_fields(dc_type: type) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(dc_type):
        if f.name in _SECTION_TYPES or f.name == "stems":
            continue  # nested sections are described separately
        meta = dict(f.metadata)
        entry: dict[str, Any] = {
            "type": _type_name(f),
            "default": _default_of(f),
            "label": meta.get("label", f.name.replace("_", " ").capitalize()),
            "help": meta.get("help"),
        }
        for key in ("min", "max", "step", "unit", "choices"):
            if key in meta:
                entry[key] = meta[key]
        out[f.name] = entry
    return out


def _type_name(f) -> str:
    raw = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "str")
    for py, name in (("bool", "bool"), ("int", "int"), ("float", "float")):
        if raw.startswith(py):
            return name
    return "str"


def _default_of(f) -> Any:
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:  # type: ignore[misc]
        return None
    return None
```

Update the imports at the top of `config.py`:

```python
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/config.py tests/test_config.py
git commit -m "feat: config field metadata and schema export for UI generation"
```

---

### Task 7: Optional explicit loop points

`LoopConfig` gains `start_s` / `end_s`. Null keeps today's auto-detection. This is what makes the waveform's loop handles draggable, and it is the precursor to multi-segment arrangement without committing to an arrangement model.

**Files:**
- Modify: `sleepmix/config.py` (`LoopConfig`)
- Modify: `sleepmix/analysis.py` (`find_loop`)
- Test: `tests/test_analysis.py` (new file)

**Interfaces:**
- Consumes: `LoopPoint`, `find_loop` (existing)
- Produces: `LoopConfig.start_s: float | None`, `LoopConfig.end_s: float | None`. When both are set, `find_loop` returns exactly that region.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis.py`:

```python
import numpy as np

from sleepmix.analysis import find_loop
from sleepmix.audio import AudioBuffer
from sleepmix.config import LoopConfig


def _tone(secs=10.0, sr=22050):
    t = np.arange(int(sr * secs)) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def test_explicit_loop_points_are_used_verbatim():
    buf = _tone()
    cfg = LoopConfig(start_s=2.0, end_s=6.0)
    lp = find_loop(buf, cfg)
    assert lp.start == int(2.0 * buf.sr)
    assert lp.end == int(6.0 * buf.sr)


def test_explicit_loop_points_are_clamped_to_the_buffer():
    buf = _tone(secs=5.0)
    cfg = LoopConfig(start_s=-1.0, end_s=99.0)
    lp = find_loop(buf, cfg)
    assert lp.start == 0
    assert lp.end == buf.n_frames


def test_omitting_loop_points_still_auto_detects():
    buf = _tone()
    lp = find_loop(buf, LoopConfig())
    assert lp.end > lp.start
    assert lp.tempo > 0


def test_partial_loop_points_fall_back_to_auto():
    buf = _tone()
    lp = find_loop(buf, LoopConfig(start_s=2.0))  # end_s omitted
    auto = find_loop(buf, LoopConfig())
    assert (lp.start, lp.end) == (auto.start, auto.end)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pipenv run pytest tests/test_analysis.py -v`
Expected: FAIL — `TypeError: LoopConfig.__init__() got an unexpected keyword argument 'start_s'`

- [ ] **Step 3: Add the config fields**

In `sleepmix/config.py`, add to `LoopConfig`:

```python
    # Explicit loop region in seconds. Both None (the default) means auto-detect.
    # Set by the UI when you drag the loop handles on the waveform.
    start_s: float | None = field(default=None, metadata={
        "label": "Loop start", "unit": "s", "min": 0.0,
        "help": "Leave empty to auto-detect a beat-aligned loop."})
    end_s: float | None = field(default=None, metadata={
        "label": "Loop end", "unit": "s", "min": 0.0,
        "help": "Leave empty to auto-detect a beat-aligned loop."})
```

- [ ] **Step 4: Honor them in `find_loop`**

In `sleepmix/analysis.py`, replace `find_loop` with:

```python
def find_loop(buf: AudioBuffer, cfg: LoopConfig) -> LoopPoint:
    """Pick a ``cfg.bars``-bar loop from the stable middle of the track.

    An explicit ``start_s``/``end_s`` pair short-circuits detection entirely —
    that is how the UI hands back a region you dragged on the waveform."""
    explicit = _explicit_loop(buf, cfg)
    if explicit is not None:
        return explicit
    try:
        return _librosa_loop(buf, cfg)
    except Exception:
        return _fixed_tempo_loop(buf, cfg)


def _explicit_loop(buf: AudioBuffer, cfg: LoopConfig) -> LoopPoint | None:
    if cfg.start_s is None or cfg.end_s is None:
        return None
    start = int(max(cfg.start_s, 0.0) * buf.sr)
    end = int(min(cfg.end_s * buf.sr, buf.n_frames))
    start = min(start, max(buf.n_frames - 1, 0))
    if end <= start:
        return None
    return LoopPoint(start=start, end=end, tempo=_estimate_tempo(buf))


def _estimate_tempo(buf: AudioBuffer) -> float:
    """Best-effort BPM, for display only — never used to place the loop here."""
    try:
        import librosa

        tempo, _ = librosa.beat.beat_track(y=buf.to_mono().data[:, 0], sr=buf.sr)
        return float(np.atleast_1d(tempo)[0])
    except Exception:
        return 120.0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_analysis.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/config.py sleepmix/analysis.py tests/test_analysis.py
git commit -m "feat: optional explicit loop points, overriding auto-detection"
```

---

### Task 8: `session.py` — memoized render context

Without staged memoization, every preview re-runs the phase vocoder and preview stops being interactive. This is the difference between ~100 ms and ~2 s.

**Files:**
- Create: `sleepmix/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `separate`, `find_loop`, `slice_loop`, `make_seamless`, `slow_and_pitch`, `cache_dir`; the `stub_separation` fixture (Task 5) in tests
- Produces:
  - `RenderSession(input_path: str, config: MixConfig, separate_fn=None)` — `separate_fn` defaults to the real `separate`; injecting it is how tests avoid a ~10 s Demucs call per session
  - `.stems() -> dict[str, AudioBuffer]` — cached across config changes
  - `.loop_point() -> LoopPoint` — invalidated by `config.loop`
  - `.prepared_loop(stem: str) -> AudioBuffer` — seamless + time-stretched; invalidated by `config.loop` or `config.tempo`
  - `.update_config(config: MixConfig) -> None` — swaps config, invalidating only what changed
  - `.stem_names() -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_session.py`:

```python
import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig
from sleepmix.session import RenderSession


def _song(path, sr=22050, secs=6.0):
    t = np.arange(int(sr * secs)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0
    save_audio(AudioBuffer(np.stack([y, y], axis=1).astype(np.float32), sr), str(path))


def test_stems_are_computed_once(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)

    calls = []
    def counting(*a, **k):
        calls.append(1)
        return stub_separation(*a, **k)

    s = RenderSession(str(song), MixConfig(), separate_fn=counting)
    s.stems()
    s.stems()
    assert len(calls) == 1


def test_changing_tempo_invalidates_prepared_loop_but_not_stems(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)

    stems_before = s.stems()
    name = s.stem_names()[0]
    loop_before = s.prepared_loop(name)

    faster = MixConfig()
    faster.tempo.speed = 0.5
    s.update_config(faster)

    assert s.stems() is stems_before, "separation must survive a tempo change"
    assert s.prepared_loop(name).n_frames != loop_before.n_frames


def test_changing_decay_invalidates_nothing_cached(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    s = RenderSession(str(song), MixConfig(), separate_fn=stub_separation)
    name = s.stem_names()[0]
    loop_before = s.prepared_loop(name)

    changed = MixConfig()
    changed.stems[0].decay.amp_end_db = -30.0
    s.update_config(changed)

    assert s.prepared_loop(name) is loop_before, "decay must not touch the loop"


def test_loop_point_respects_explicit_config(tmp_path, stub_separation):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.loop.start_s = 1.0
    cfg.loop.end_s = 3.0
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)
    lp = s.loop_point()
    assert lp.start == int(1.0 * 22050)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.session'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/session.py`:

```python
"""A song held open for interactive work.

Rendering a preview means answering "what does this sound like at this point in
the decay arc" in about 100 ms. That is only possible if the expensive stages
before decay — separation, loop detection, time-stretching — are not redone on
every keystroke. This class stages those results and invalidates each one only
when the part of the config it actually depends on changes.

Ownership: one session per open song. It holds decoded audio in memory, so the
server should not keep an unbounded number of them alive.
"""
from __future__ import annotations

from dataclasses import asdict

from .analysis import LoopPoint, find_loop, slice_loop
from .audio import AudioBuffer
from .config import MixConfig
from .looping import make_seamless
from .paths import cache_dir
from .separation import separate
from .timestretch import slow_and_pitch


class RenderSession:
    def __init__(self, input_path: str, config: MixConfig,
                 separate_fn=None) -> None:
        self.input_path = input_path
        self.config = config
        # Injectable so tests can skip a ~10 s Demucs call per session.
        self._separate_fn = separate_fn or separate
        self._stems: dict[str, AudioBuffer] | None = None
        self._loop_point: LoopPoint | None = None
        self._prepared: dict[str, AudioBuffer] = {}
        self._loop_key = self._key(config.loop)
        self._tempo_key = self._key(config.tempo)

    # -- staged results -------------------------------------------------
    def stems(self) -> dict[str, AudioBuffer]:
        if self._stems is None:
            self._stems = self._separate_fn(
                self.input_path, self.config.separation_model,
                cache_dir=str(cache_dir()))
        return self._stems

    def stem_names(self) -> list[str]:
        return list(self.stems().keys())

    def loop_point(self) -> LoopPoint:
        if self._loop_point is None:
            self._loop_point = find_loop(self._reference(), self.config.loop)
        return self._loop_point

    def prepared_loop(self, stem: str) -> AudioBuffer:
        """The stem's loop, made seamless and time-stretched — ready to decay."""
        if stem not in self._prepared:
            buf = self.stems()[stem]
            loop = slice_loop(buf, self.loop_point())
            loop = make_seamless(loop, self.config.loop.crossfade_ms)
            self._prepared[stem] = slow_and_pitch(
                loop, self.config.tempo.speed, self.config.tempo.pitch_semitones)
        return self._prepared[stem]

    # -- invalidation ---------------------------------------------------
    def update_config(self, config: MixConfig) -> None:
        """Swap in a new config, discarding only the stages it invalidates."""
        loop_key = self._key(config.loop)
        tempo_key = self._key(config.tempo)
        if loop_key != self._loop_key:
            self._loop_point = None
            self._prepared.clear()
        elif tempo_key != self._tempo_key:
            self._prepared.clear()
        if config.separation_model != self.config.separation_model:
            self._stems = None
            self._loop_point = None
            self._prepared.clear()
        self.config = config
        self._loop_key = loop_key
        self._tempo_key = tempo_key

    # -- internals ------------------------------------------------------
    def _reference(self) -> AudioBuffer:
        """Sum of all stems — what loop detection runs against."""
        import numpy as np

        buffers = list(self.stems().values())
        n = max(b.n_frames for b in buffers)
        ch = max(b.n_channels for b in buffers)
        acc = np.zeros((n, ch), dtype=np.float32)
        for b in buffers:
            x = b.with_channels(ch).data
            acc[:x.shape[0]] += x
        return AudioBuffer(acc, buffers[0].sr)

    @staticmethod
    def _key(section) -> tuple:
        return tuple(sorted(asdict(section).items()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_session.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sleepmix/session.py tests/test_session.py
git commit -m "feat: RenderSession memoizes separation, loop and stretch stages"
```

---

### Task 9: `preview.py` — window rendering

The payoff. ~33 ms per stem per window, measured.

**Files:**
- Create: `sleepmix/preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `RenderSession` (Task 8), `plan_iterations` / `decayed_iteration` (Task 3), `apply_reverb`
- Produces:
  - `preview_iteration_index(session, progress: float) -> tuple[int, int]` returning `(iteration, n_iterations)`
  - `render_window(session, progress: float, stems: list[str] | None = None, reverb: bool = True) -> AudioBuffer`

- [ ] **Step 1: Write the failing test**

Create `tests/test_preview.py`:

```python
import time

import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig, StemConfig
from sleepmix.disintegration import decayed_iteration
from sleepmix.preview import preview_iteration_index, render_window
from sleepmix.session import RenderSession


def _song(path, sr=22050, secs=6.0):
    t = np.arange(int(sr * secs)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0
    save_audio(AudioBuffer(np.stack([y, y], axis=1).astype(np.float32), sr), str(path))


def _session(tmp_path, sep):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    return RenderSession(str(song), cfg, separate_fn=sep)


def test_window_matches_decayed_iteration_pre_reverb(tmp_path, stub_separation):
    """The preview is the same computation the render performs.

    Compared pre-reverb because reverb is applied per-window here and has no
    tail from the preceding iteration — see the fidelity caveat in the spec."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]

    progress = 0.7
    out = render_window(s, progress, stems=[name], reverb=False)
    i, n = preview_iteration_index(s, progress)
    expected = decayed_iteration(
        s.prepared_loop(name), i, n, s.config.stems[0].decay, s.config.seed, name)
    assert np.array_equal(out.data, expected.data)


def test_iteration_index_spans_the_arc(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    first, n = preview_iteration_index(s, 0.0)
    last, _ = preview_iteration_index(s, 1.0)
    assert first == 0
    assert last == n - 1
    assert n > 1


def test_soloing_stems_changes_the_result(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    names = s.stem_names()
    assert len(names) >= 2, "the stub provides four distinct stems"
    a = render_window(s, 0.5, stems=names[:1], reverb=False)
    b = render_window(s, 0.5, stems=names, reverb=False)
    assert not np.array_equal(a.data, b.data)


def test_window_is_finite_and_reverb_is_applied(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    dry = render_window(s, 0.5, stems=[name], reverb=False)
    wet = render_window(s, 0.5, stems=[name], reverb=True)
    assert np.all(np.isfinite(wet.data))
    assert not np.array_equal(dry.data, wet.data)


def test_window_is_fast_once_the_session_is_warm(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    render_window(s, 0.5, stems=[name])          # warm the session
    t0 = time.perf_counter()
    render_window(s, 0.6, stems=[name])
    assert time.perf_counter() - t0 < 1.0, "preview must stay interactive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.preview'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/preview.py`:

```python
"""Render one point in the decay arc, without rendering what precedes it.

``apply_decay`` is a pure function of progress — iteration 400 does not depend
on iterations 1..399 — so auditioning "what does this sound like two thirds of
the way through" costs a single loop iteration rather than twenty minutes. That
is the whole basis of interactive tuning here.

A preview is always a *specific iteration*: the one nearest the requested point
in the arc. That makes it exactly reproducible against the corresponding part of
a full render (pre-reverb), rather than an approximation of it.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer, silence
from .config import StemConfig
from .disintegration import decayed_iteration, plan_iterations
from .effects import apply_reverb
from .session import RenderSession
from .util import db_to_amp


def preview_iteration_index(session: RenderSession, progress: float) -> tuple[int, int]:
    """Map a point in the arc to ``(iteration, n_iterations)``.

    Uses the same ``plan_iterations`` the batch renderer uses, so the mapping
    cannot drift between preview and render."""
    cfg = session.config
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    n_iter, _ = plan_iterations(
        loop.n_frames, target_frames, cfg.output.cycle_crossfade_ms, loop.sr)
    p = float(np.clip(progress, 0.0, 1.0))
    return int(round(p * (n_iter - 1))), n_iter


def render_window(
    session: RenderSession,
    progress: float,
    stems: list[str] | None = None,
    reverb: bool = True,
) -> AudioBuffer:
    """One loop iteration at ``progress``, summed over ``stems``.

    ``stems`` defaults to every stem the session has. Pass a subset to solo."""
    cfg = session.config
    names = stems if stems is not None else session.stem_names()
    iteration, n_iter = preview_iteration_index(session, progress)

    acc: np.ndarray | None = None
    sr = 0
    for name in names:
        sc = _stem_config(cfg.stems, name)
        if not sc.enabled:
            continue
        loop = session.prepared_loop(name)
        sr = loop.sr
        chunk = decayed_iteration(loop, iteration, n_iter, sc.decay, cfg.seed, name)
        x = chunk.with_channels(cfg.output.channels).data
        if abs(sc.gain_db) > 1e-6:
            x = x * db_to_amp(sc.gain_db)
        if acc is None:
            acc = x.copy()
        else:
            m = min(acc.shape[0], x.shape[0])
            acc[:m] += x[:m]

    if acc is None:
        return silence(1, cfg.output.channels, cfg.output.sample_rate)

    out = AudioBuffer(acc, sr)
    if reverb:
        out = apply_reverb(out, cfg.reverb)
    return out


def _stem_config(configured: list[StemConfig], name: str) -> StemConfig:
    """The configured stem, or defaults when the session has a stem the config
    doesn't mention (e.g. the single 'mix' stem from the no-Demucs fallback)."""
    for sc in configured:
        if sc.name == name:
            return sc
    return StemConfig(name=name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_preview.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sleepmix/preview.py tests/test_preview.py
git commit -m "feat: render a single window of the decay arc for audition"
```

---

### Task 10: Export the new surface and document it

**Files:**
- Modify: `sleepmix/__init__.py`
- Create: `docs/architecture.md`
- Create: `docs/project-state.md`
- Modify: `README.md` (Development section)

- [ ] **Step 1: Export the new public names**

In `sleepmix/__init__.py`, add to the existing exports:

```python
from .preview import render_window, preview_iteration_index
from .progress import CancelToken, Cancelled, ProgressEvent, ProgressReporter
from .session import RenderSession
```

and extend `__all__` with `"render_window"`, `"preview_iteration_index"`, `"RenderSession"`, `"ProgressReporter"`, `"ProgressEvent"`, `"CancelToken"`, `"Cancelled"`.

- [ ] **Step 2: Verify the package still imports cleanly**

Run: `pipenv run python -c "import sleepmix; print(sorted(sleepmix.__all__))"`
Expected: prints the list including the new names, no import errors.

- [ ] **Step 3: Write `docs/architecture.md`**

Cover, with reference to actual files: the stage pipeline and what each module owns; why `apply_decay` being a pure function of progress is the load-bearing property; the graceful-degradation policy for optional dependencies (never import at module scope); the `RenderSession` staging table and what invalidates each stage; the progress/cancellation contract; and where data lives (`paths.py`).

- [ ] **Step 4: Write `docs/project-state.md`**

Record: which parts of the spec are built and which are not (server, store, UI are Plans 2 and 3); the accepted RNG behavior change and that pre-existing renders are unreproducible; the preview reverb-tail fidelity caveat; that the silent Demucs fallback is still silent and is scheduled for Plan 2; and that the librosa first-run JIT stall is not yet warmed.

- [ ] **Step 5: Update the README Development section**

Change the install line to `pipenv install --dev` and the test line to `pipenv run pytest -q`, and add a sentence noting that tests are isolated from real data by `tests/conftest.py`.

- [ ] **Step 6: Run the full suite one final time**

Run: `pipenv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add sleepmix/__init__.py docs/architecture.md docs/project-state.md README.md
git commit -m "docs: architecture and project state for the core hooks layer"
```

---

## What this plan does not cover

Per the spec's scope, and deferred to later plans:

- **Plan 2 — server and store:** FastAPI app, SSE progress endpoint, background job manager, SQLite library (songs/presets/renders), waveform peak computation, surfacing the silent Demucs fallback as explicit song state, and the librosa warm-up pass on startup.
- **Plan 3 — React SPA:** Library, Song view, Mixer, Render screens; schema-driven controls; Web Audio buffer swapping at loop boundaries.
- **Future:** segment selection and arrangement; output length as an arrangement property; bundled desktop app.
