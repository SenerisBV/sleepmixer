# The Ghost (Plan 5, Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sleepmix night` plays loops of real music that give way to drones built from their own spectra, one source at a time, with each handover hidden behind the ghost of the piece that just ended.

**Architecture:** `sleepmix prepare` does the expensive work ahead of time and writes an audio-free `SourceProfile` per song. The planner schedules sources to take turns, emits a source voice and its ghost as a co-located *pair*, and varies the pair's gain balance across the night. The palette gains one branch for playing a prepared loop. Nothing about the arc, the nested clocks, block independence or the speech layer changes.

**Tech Stack:** Python 3.10+, numpy, scipy, soundfile, click. Demucs / librosa / pyrubberband are used only by `prepare`, all optional with existing fallbacks. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-18-night-ghost-design.md`

## Global Constraints

- **`sleepmix/night/` may import from `sleepmix/`, never the reverse.** One scope-conditional exception exists for `cli.py` (function-local imports only). An AST guard enforces this (`tests/import_guard.py`).
- **`night/plan.py`, `clock.py`, `context.py`, `sky.py` and the new `night/sources.py` may not import anything that generates or decodes audio.** `sources.py` joins that list; `night/pitch.py` and `night/prepare.py` are audio modules and must be added to `plan.py`'s forbidden set.
- **Block independence:** block *N* of the music layer rendered alone must stay bit-identical to blocks 0..*N* rendered in sequence. Verified holding today. Nothing live may enter `stream.py`.
- **No transients.** Every voice fades in and out; the fade is applied in `palette.render_voice` and again over the padded buffer in `stream._rendered`.
- **Degrade silently.** Every error path ends in less sound, never different sound, never no stream. A profile that will not load costs its voice, not the night.
- **Preparation never runs at bedtime.** `sleepmix night` must not invoke separation, loop detection or time-stretching. It reads prepared profiles or it runs pure Phase 1.
- **You never hear the unprocessed loop alone.** The birth ratio is capped below 1.0 at every hour.
- Optional/heavy dependencies are imported inside the function that needs them.
- Tests live in `tests/` and run under `pipenv run pytest -q`. Current baseline: **534 passing.**

## The plan's code is a draft. Expect to find bugs in it.

Phase 1's reference code contained **six real defects**, all found by the people implementing it and confirmed by review. They are listed here because the same hand wrote this plan and the same mistakes are available:

| What | Where it hid |
|---|---|
| `rfft(x, axis=0)` then `irfft(...)` with no `axis` — **twice** | 2-D stereo FFT helpers; the failing assertion read `n_channels == 44100` |
| A file that decoded with zero frames looped forever | `RoomSource._advance` accepted it; the cursor was instantly at the end |
| `rfft` with `n=0` on an empty buffer | `through_a_wall` on a zero-length read |
| A config's `enabled` flag ignored | `_bed` gated on `noise_type` only |
| `if seconds else None` treating `0` as "no limit" | the CLI |
| A DSP constant off by 5× | the band-limit shoulder |

**Named hazards for this plan specifically** — check each one deliberately rather than trusting the code below:

1. **Any `numpy` transform on a `(n_frames, n_channels)` array needs an explicit `axis=0` on both the forward and the inverse.** This is the one that shipped twice.
2. **Every buffer length can be zero.** A loop file can be empty, a pitch set can be empty, a profile list can be empty, `n_frames` can be zero. Guard before dividing, before `rfft`, before indexing `[0]`.
3. **Tiling a loop to a target length** is off-by-one country. Assert the result's length exactly.
4. **A frozen dataclass gaining optional fields** silently accepts wrong keyword order at every call site. Use keywords.
5. **Anything read from disk is attacker-shaped**, in the sense that it was written by an earlier version of this code. A profile missing a key must degrade, not raise.

If you find a defect, fix it, add a regression test, and say so plainly in your report. That is the expected outcome, not an exception.

## File structure

| File | Responsibility |
|---|---|
| `sleepmix/night/pitch.py` | **New.** `pitch_set(buf) -> tuple[float, ...]` — spectral peak-picking with octave folding. Audio in, numbers out. Imported only by `prepare.py`. |
| `sleepmix/night/sources.py` | **New.** `SourceProfile`, its JSON persistence, `load_profiles(directory)`, `sources_directory()`. **No audio imports** — this is what lets `plan.py` see profiles. |
| `sleepmix/night/prepare.py` | **New.** The expensive pipeline: separate → find loops → stretch → analyse → write. Only ever run by `sleepmix prepare`. |
| `sleepmix/night/plan.py` | **Modified.** `Voice` gains `source_id`, `loop_index`, `gain`. A `SourceSchedule` decides who holds the stage. Voice emission gains the source/ghost pair, the birth ratio, and outliving ghosts. |
| `sleepmix/night/palette.py` | **Modified.** `render_voice` gains a `"source"` branch that plays a prepared loop, with a small loop cache. |
| `sleepmix/night/context.py` | **Modified.** `NightContext` gains `sources: tuple[SourceProfile, ...]`, so `plan_voices(ctx, sr, ...)` keeps its signature and profiles become part of the dusk snapshot. |
| `sleepmix/cli.py` | **Modified.** `sleepmix prepare`; `night` loads profiles and says which mode it is in. |
| `tests/test_night_pitch.py` … `tests/test_night_prepare.py` | One test module per new source module, plus additions to the existing night tests. |

---

### Task 1: The pitch set — what is actually in the material

**Files:**
- Create: `sleepmix/night/pitch.py`
- Test: `tests/test_night_pitch.py`

**Interfaces:**
- Consumes: `sleepmix.audio.AudioBuffer`.
- Produces:
  - `pitch_set(buf: AudioBuffer, max_pitches: int = 6) -> tuple[float, ...]` — dominant frequencies, octave-folded into one band, ascending, possibly empty
  - `FOLD_LOW_HZ = 55.0`, `FOLD_HIGH_HZ = 110.0`
  - `MIN_PEAK_FRACTION = 0.02`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_pitch.py`:

```python
"""What is actually in the material, as numbers.

The ghost's drones sound at frequencies physically present in the source, not
at the notes of a key some estimator inferred from it. That is the whole
difference between this and chroma detection, and it is why these tests
synthesize known partials and demand them back rather than asserting anything
musicological.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night.pitch import (
    FOLD_HIGH_HZ, FOLD_LOW_HZ, MIN_PEAK_FRACTION, pitch_set,
)

SR = 22050


def _tone(freqs, seconds=2.0, sr=SR, amps=None):
    t = np.arange(int(seconds * sr)) / sr
    amps = amps or [1.0] * len(freqs)
    y = sum(a * np.sin(2 * np.pi * f * t) for f, a in zip(freqs, amps))
    y = (y / max(np.abs(y).max(), 1e-9) * 0.5).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def _folded(hz):
    """Where a frequency should land after octave folding."""
    while hz >= FOLD_HIGH_HZ:
        hz /= 2.0
    while hz < FOLD_LOW_HZ:
        hz *= 2.0
    return hz


def test_a_single_tone_gives_one_pitch():
    found = pitch_set(_tone([220.0]))
    assert len(found) == 1
    assert found[0] == pytest.approx(_folded(220.0), abs=1.5)


def test_three_tones_give_three_pitches():
    found = pitch_set(_tone([110.0, 164.81, 220.0]))
    assert len(found) == 3


def test_octaves_fold_onto_each_other():
    """A tone and its octave are the same pitch class and must not be two."""
    found = pitch_set(_tone([110.0, 220.0, 440.0]))
    assert len(found) == 1
    assert found[0] == pytest.approx(110.0, abs=1.5)


def test_every_pitch_lands_inside_the_fold_band():
    found = pitch_set(_tone([55.0, 233.08, 880.0, 1760.0]))
    assert found
    for hz in found:
        assert FOLD_LOW_HZ <= hz < FOLD_HIGH_HZ


def test_the_set_is_ascending_and_has_no_duplicates():
    found = pitch_set(_tone([146.83, 220.0, 110.0, 329.63]))
    assert list(found) == sorted(found)
    assert len(set(found)) == len(found)


def test_max_pitches_is_honoured():
    found = pitch_set(_tone([110.0, 123.47, 130.81, 146.83, 164.81, 174.61,
                             196.0, 207.65]), max_pitches=3)
    assert len(found) <= 3


def test_a_quiet_partial_below_the_threshold_is_ignored():
    loud_only = pitch_set(_tone([110.0, 164.81], amps=[1.0, 0.001]))
    assert len(loud_only) == 1


def test_noise_does_not_produce_a_confident_pitch_set():
    """Broadband noise has no peaks worth calling pitches."""
    rng = np.random.default_rng(0)
    x = (rng.standard_normal((SR * 2, 2)) * 0.3).astype(np.float32)
    assert len(pitch_set(AudioBuffer(x, SR))) <= 2


def test_silence_gives_an_empty_set_rather_than_raising():
    quiet = AudioBuffer(np.zeros((SR, 2), dtype=np.float32), SR)
    assert pitch_set(quiet) == ()


def test_an_empty_buffer_gives_an_empty_set_rather_than_raising():
    empty = AudioBuffer(np.zeros((0, 2), dtype=np.float32), SR)
    assert pitch_set(empty) == ()


def test_a_mono_buffer_is_accepted():
    t = np.arange(SR) / SR
    y = (0.5 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    assert len(pitch_set(AudioBuffer(y, SR))) == 1


def test_the_result_is_reproducible():
    buf = _tone([110.0, 164.81])
    assert pitch_set(buf) == pitch_set(buf)


def test_the_threshold_constant_is_a_fraction():
    assert 0.0 < MIN_PEAK_FRACTION < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_pitch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.pitch'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/pitch.py`:

```python
"""The frequencies actually present in a piece of material.

A ghost is built from its source's own spectrum, so this answers a specific
question rather than a musicological one: *what is physically in this loop*.
Chroma or key detection would give a tidier answer and a less honest one — it
would tell you what key a listener would name, and the ghost would then sound
at notes the source may never have played.

Octave folding is what keeps the set small and useful. A bass note and its
third harmonic are the same pitch class as far as a drone is concerned, and
folding lets a ghost sound an octave away from where the source did without
inventing a pitch that was not there.

Audio in, numbers out. Nothing downstream of this module ever sees a buffer,
which is what lets ``night/sources.py`` and ``night/plan.py`` stay audio-free.
"""
from __future__ import annotations

import numpy as np

from ..audio import AudioBuffer

# The band every pitch is folded into — one octave, low enough that a drone
# built here sits under rather than over whatever else is sounding.
FOLD_LOW_HZ = 55.0
FOLD_HIGH_HZ = 110.0

# A peak must carry at least this fraction of the strongest peak's magnitude
# to count as a pitch. Below it, the "peak" is the shoulder of a real one or
# it is noise.
MIN_PEAK_FRACTION = 0.02

# Frequencies outside this are not pitches for this purpose: below it is
# rumble and room, above it there is nothing a drone should chase.
_MIN_HZ = 40.0
_MAX_HZ = 4000.0

# Two folded pitches closer than this are the same pitch.
_MERGE_CENTS = 45.0


def _fold(hz: float) -> float:
    """Bring ``hz`` into ``[FOLD_LOW_HZ, FOLD_HIGH_HZ)`` by octaves."""
    if hz <= 0:
        return 0.0
    while hz >= FOLD_HIGH_HZ:
        hz /= 2.0
    while hz < FOLD_LOW_HZ:
        hz *= 2.0
    return hz


def pitch_set(buf: AudioBuffer, max_pitches: int = 6) -> tuple[float, ...]:
    """The dominant frequencies in ``buf``, octave-folded, ascending.

    Returns an empty tuple for silence, for an empty buffer, or for material
    with no peak worth the name — all three are ordinary rather than
    exceptional, and a caller with no pitches simply has no ghost to build.
    """
    mono = buf.to_mono().data[:, 0]
    n = len(mono)
    if n < 64 or not np.any(mono):
        return ()

    windowed = mono * np.hanning(n).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, 1.0 / buf.sr)

    in_band = (freqs >= _MIN_HZ) & (freqs <= _MAX_HZ)
    spectrum = np.where(in_band, spectrum, 0.0)
    if not np.any(spectrum):
        return ()

    # A local maximum, so the shoulders of one partial do not become three.
    peaks = np.zeros(len(spectrum), dtype=bool)
    peaks[1:-1] = (spectrum[1:-1] > spectrum[:-2]) & (spectrum[1:-1] >= spectrum[2:])
    peak_idx = np.flatnonzero(peaks)
    if peak_idx.size == 0:
        return ()

    strongest = float(spectrum[peak_idx].max())
    peak_idx = peak_idx[spectrum[peak_idx] >= strongest * MIN_PEAK_FRACTION]
    if peak_idx.size == 0:
        return ()

    # Loudest first, so merging keeps the strongest of a cluster.
    peak_idx = peak_idx[np.argsort(spectrum[peak_idx])[::-1]]

    kept: list[float] = []
    for idx in peak_idx:
        folded = _fold(float(freqs[idx]))
        if folded <= 0:
            continue
        if any(abs(1200.0 * np.log2(folded / k)) < _MERGE_CENTS for k in kept):
            continue
        kept.append(folded)
        if len(kept) >= max_pitches:
            break

    return tuple(sorted(kept))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_pitch.py -q`
Expected: PASS, 13 passed

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, 534 + 13 = 547

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/pitch.py tests/test_night_pitch.py
git commit -m "feat: the frequencies actually in the material"
```

---

### Task 2: `SourceProfile` — everything the planner may know about a song

**Files:**
- Create: `sleepmix/night/sources.py`
- Test: `tests/test_night_sources.py`

**Interfaces:**
- Consumes: `sleepmix.paths.data_dir`. **Nothing that touches audio.**
- Produces:
  - `SourceProfile` frozen dataclass: `source_id: str`, `loop_paths: tuple[str, ...]`, `loop_frames: tuple[int, ...]`, `pitch_set: tuple[float, ...]`, `sr: int`
  - `PROFILE_SUFFIX = ".night.json"`
  - `sources_directory() -> str`, `profiles_directory() -> str`
  - `write_profile(profile: SourceProfile) -> str`
  - `load_profiles() -> tuple[SourceProfile, ...]` — never raises
  - `pitch_distance(a: SourceProfile, b: SourceProfile) -> float`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_sources.py`:

```python
"""What the planner is allowed to know about a song.

Everything here is a path, a count or a number. No audio, ever — that is what
lets `night/plan.py` import this module without breaking the guard that keeps
an eight-hour night plannable in microseconds.
"""
import json
import os

import pytest

from sleepmix.night import sources as sources_mod
from sleepmix.night.sources import (
    PROFILE_SUFFIX, SourceProfile, load_profiles, pitch_distance,
    profiles_directory, sources_directory, write_profile,
)


def _profile(source_id="a", pitches=(55.0, 82.5), loops=("/tmp/x.wav",),
             frames=(220500,), sr=44100):
    return SourceProfile(source_id=source_id, loop_paths=tuple(loops),
                         loop_frames=tuple(frames), pitch_set=tuple(pitches),
                         sr=sr)


def test_sources_module_imports_no_audio():
    from .import_guard import forbidden_imports
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = forbidden_imports(
        root / "sleepmix" / "night" / "sources.py", root,
        {"numpy", "scipy", "soundfile", "pedalboard", "sleepmix.audio",
         "sleepmix.effects", "sleepmix.night.pitch", "sleepmix.night.prepare",
         "sleepmix.night.palette", "sleepmix.night.stream"})
    assert offenders == set(), f"sources.py imports audio: {offenders}"


def test_a_profile_round_trips_through_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    written = write_profile(_profile())
    assert written.endswith(PROFILE_SUFFIX)
    assert load_profiles() == (_profile(),)


def test_profiles_come_back_in_a_stable_order(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    for name in ("c", "a", "b"):
        write_profile(_profile(source_id=name))
    assert [p.source_id for p in load_profiles()] == ["a", "b", "c"]


def test_no_profiles_directory_is_an_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "nothing-here"))
    assert load_profiles() == ()


def test_a_corrupt_profile_is_skipped_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    bad = os.path.join(profiles_directory(), "bad" + PROFILE_SUFFIX)
    with open(bad, "w") as fh:
        fh.write("{ this is not json")
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_missing_a_key_is_skipped_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    partial = os.path.join(profiles_directory(), "partial" + PROFILE_SUFFIX)
    with open(partial, "w") as fh:
        json.dump({"source_id": "partial"}, fh)
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_with_no_loops_is_skipped(tmp_path, monkeypatch):
    """A profile that names no material cannot produce a voice."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    write_profile(_profile(source_id="empty", loops=(), frames=()))
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_whose_loops_and_frames_disagree_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    write_profile(_profile(source_id="ragged", loops=("/a.wav", "/b.wav"),
                           frames=(100,)))
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_the_directories_live_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert str(tmp_path) in sources_directory()
    assert sources_directory().endswith("sources")
    assert str(tmp_path) in profiles_directory()


def test_pitch_distance_is_zero_for_identical_sets():
    assert pitch_distance(_profile(), _profile()) == pytest.approx(0.0)


def test_pitch_distance_grows_with_disagreement():
    near = pitch_distance(_profile(pitches=(55.0, 82.5)),
                          _profile(pitches=(56.0, 83.0)))
    far = pitch_distance(_profile(pitches=(55.0, 82.5)),
                         _profile(pitches=(75.0, 104.0)))
    assert 0.0 < near < far


def test_pitch_distance_survives_an_empty_set():
    d = pitch_distance(_profile(pitches=()), _profile())
    assert d >= 0.0 and d == d  # finite, not NaN


def test_a_profile_is_frozen():
    with pytest.raises(Exception):
        _profile().source_id = "other"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_sources.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.sources'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/sources.py`:

```python
"""What the planner is allowed to know about a song.

A ``SourceProfile`` is the whole of the interface between the expensive half
of this feature and the cheap half. ``prepare`` separates, finds loops,
stretches and analyses; everything after that reads a path, a frame count and
a list of frequencies.

**This module imports no audio, and that is load-bearing rather than tidy.**
``night/plan.py`` imports it, and `plan.py` is under an AST guard that keeps an
eight-hour night plannable in microseconds. A profile is data about audio, not
audio.

Every failure here is a skip. A profile written by an older version, half
written, or naming a file that has since moved is an ordinary thing to find in
a directory a person drops files into — and the correct response is one fewer
source, not a night that will not start.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass

from ..paths import data_dir

PROFILE_SUFFIX = ".night.json"


@dataclass(frozen=True)
class SourceProfile:
    """One prepared song, as numbers and paths."""

    source_id: str
    loop_paths: tuple[str, ...]
    loop_frames: tuple[int, ...]
    pitch_set: tuple[float, ...]
    sr: int


def sources_directory() -> str:
    """Where songs are dropped. Created on demand."""
    path = os.path.join(str(data_dir()), "sources")
    os.makedirs(path, exist_ok=True)
    return path


def profiles_directory() -> str:
    """Where ``prepare`` writes what it worked out. Created on demand."""
    path = os.path.join(str(data_dir()), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def write_profile(profile: SourceProfile) -> str:
    """Write ``profile`` and return its path.

    Written to a temporary name and renamed, so a `prepare` interrupted here
    leaves either the previous profile or none — the same discipline
    ``separation._write_cache`` uses for the same reason.
    """
    final = os.path.join(profiles_directory(),
                         profile.source_id + PROFILE_SUFFIX)
    staging = final + ".partial"
    with open(staging, "w") as fh:
        json.dump(asdict(profile), fh, indent=2, sort_keys=True)
    os.replace(staging, final)
    return final


def _read_profile(path: str) -> SourceProfile | None:
    """One profile, or ``None`` if it is unusable for any reason."""
    try:
        with open(path) as fh:
            raw = json.load(fh)
        profile = SourceProfile(
            source_id=str(raw["source_id"]),
            loop_paths=tuple(str(p) for p in raw["loop_paths"]),
            loop_frames=tuple(int(n) for n in raw["loop_frames"]),
            pitch_set=tuple(float(f) for f in raw["pitch_set"]),
            sr=int(raw["sr"]),
        )
    except Exception:
        return None

    # A profile naming no material cannot produce a voice, and one whose
    # paths and lengths disagree would index off the end of one of them.
    if not profile.loop_paths:
        return None
    if len(profile.loop_paths) != len(profile.loop_frames):
        return None
    if any(n <= 0 for n in profile.loop_frames):
        return None
    return profile


def load_profiles() -> tuple[SourceProfile, ...]:
    """Every usable profile, in a stable order. Never raises.

    Order is by ``source_id`` rather than by directory order, so the same set
    of files produces the same night on two machines.
    """
    try:
        names = sorted(n for n in os.listdir(profiles_directory())
                       if n.endswith(PROFILE_SUFFIX))
    except OSError:
        return ()

    found = []
    for name in names:
        profile = _read_profile(os.path.join(profiles_directory(), name))
        if profile is not None:
            found.append(profile)
    return tuple(sorted(found, key=lambda p: p.source_id))


def pitch_distance(a: SourceProfile, b: SourceProfile) -> float:
    """How far apart two profiles sit tonally, in cents.

    Used by the planner to choose which source takes the stage next, so that
    the overlap during a handover is consonant rather than a collision. For
    each pitch in the smaller set, the distance to its nearest neighbour in the
    other; averaged. An empty set on either side is maximally distant rather
    than an error, which puts a pitchless source last in the running.
    """
    if not a.pitch_set or not b.pitch_set:
        return float(_MAX_DISTANCE_CENTS)

    total = 0.0
    for hz in a.pitch_set:
        total += min(abs(1200.0 * math.log2(hz / other))
                     for other in b.pitch_set)
    return total / len(a.pitch_set)


# One octave. Two pitch sets cannot be further apart than this after folding.
_MAX_DISTANCE_CENTS = 1200.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_sources.py -q`
Expected: PASS, 14 passed

- [ ] **Step 5: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, 561

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/sources.py tests/test_night_sources.py
git commit -m "feat: what the planner is allowed to know about a song"
```

---

### Task 3: `sleepmix prepare` — the expensive half, done when it suits

**Files:**
- Create: `sleepmix/night/prepare.py`
- Modify: `sleepmix/cli.py` (add the `prepare` command)
- Test: `tests/test_night_prepare.py`

**Interfaces:**
- Consumes: `sleepmix.audio` (`load_audio`, `save_audio`, `sum_buffers`), `sleepmix.separation.separate`, `sleepmix.analysis` (`find_loop`, `slice_loop`), `sleepmix.looping.make_seamless`, `sleepmix.timestretch.slow_and_pitch`, `sleepmix.config.LoopConfig`, `night.pitch.pitch_set`, `night.sources`.
- Produces:
  - `LOOPS_PER_SOURCE = 3`, `LOOP_BARS = 4`, `STRETCH_SPEED = 0.6`, `DROP_STEMS = ("drums",)`
  - `prepare_source(path: str, sr: int = 44100) -> SourceProfile | None`
  - `prepare_all(progress: Callable[[str], None] | None = None) -> tuple[SourceProfile, ...]`
  - `source_id_for(path: str) -> str`

> **Note.** The spec says the pitch set holds "the frequencies actually present in each loop". This ships **one pooled set per source**, computed across all of that source's loops, because `SourceProfile` carries one set and a ghost of *this song* is the more useful object than a ghost of *this loop* — the handover preference reasons at song level too. Record the simplification in Task 8's docs rather than silently differing from the spec.

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_prepare.py`:

```python
"""The expensive half, and the promise that it never runs at bedtime.

Demucs on a laptop spins the fans for minutes, next to the bed. Everything
here exists so that `sleepmix night` can be instant and silent about it, and
the last test in this file is the one that keeps that true.
"""
import os

import numpy as np
import pytest
import soundfile as sf

from sleepmix.night import prepare as prepare_mod
from sleepmix.night.prepare import (
    LOOPS_PER_SOURCE, prepare_all, prepare_source, source_id_for,
)
from sleepmix.night.sources import load_profiles, sources_directory

SR = 22050


def _write_song(path, seconds=30.0, sr=SR, freqs=(110.0, 164.81)):
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    y = (y / np.abs(y).max() * 0.5).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return str(path)


@pytest.fixture(autouse=True)
def _stub_separation(monkeypatch):
    """Demucs is not installed here and must never be needed by a test."""
    from sleepmix.audio import load_audio

    def fake_separate(input_path, model="htdemucs_ft", cache_dir=None):
        src = load_audio(str(input_path))
        return {"other": src, "drums": src}

    monkeypatch.setattr(prepare_mod, "separate", fake_separate)


def test_a_source_id_is_stable_for_a_path():
    assert source_id_for("/a/b/Song.wav") == source_id_for("/a/b/Song.wav")


def test_a_source_id_differs_between_paths():
    assert source_id_for("/a/one.wav") != source_id_for("/a/two.wav")


def test_a_source_id_is_filesystem_safe():
    ident = source_id_for("/a/b/Weird Name (mix) #2.wav")
    assert ident and all(c.isalnum() or c in "-_" for c in ident)


def test_preparing_a_song_produces_loops_and_pitches(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav")
    profile = prepare_source(song, sr=SR)
    assert profile is not None
    assert len(profile.loop_paths) == LOOPS_PER_SOURCE
    assert len(profile.loop_frames) == LOOPS_PER_SOURCE
    assert profile.pitch_set
    assert profile.sr == SR


def test_the_loop_files_actually_exist_and_match_their_frame_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for path, frames in zip(profile.loop_paths, profile.loop_frames):
        assert os.path.exists(path)
        info = sf.info(path)
        assert info.frames == frames


def test_the_loops_are_short_enough_to_carry_no_phrase(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for frames in profile.loop_frames:
        assert 1.0 <= frames / profile.sr <= 40.0


def test_dropped_stems_do_not_reach_the_loops(tmp_path, monkeypatch):
    """Drums looping under you at 2 AM is what the render defaults already
    turn off by hand."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    seen = {}

    real = prepare_mod._kept_stems

    def spy(stems):
        kept = real(stems)
        seen["names"] = sorted(kept)
        return kept

    monkeypatch.setattr(prepare_mod, "_kept_stems", spy)
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    assert "drums" not in seen["names"]
    assert "other" in seen["names"]


def test_preparing_writes_a_profile_that_loads_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    loaded = load_profiles()
    assert len(loaded) == 1
    assert loaded[0].pitch_set


def test_prepare_all_walks_the_sources_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    _write_song(os.path.join(sources_directory(), "two.wav"), freqs=(146.83,))
    assert len(prepare_all()) == 2
    assert len(load_profiles()) == 2


def test_prepare_all_on_an_empty_folder_is_an_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    assert prepare_all() == ()


def test_prepare_all_is_idempotent(tmp_path, monkeypatch):
    """Re-running costs nothing for an unchanged source."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    first = prepare_all()
    calls = {"n": 0}
    real = prepare_mod.prepare_source

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prepare_mod, "prepare_source", counted)
    second = prepare_all()
    assert calls["n"] == 0
    assert [p.source_id for p in first] == [p.source_id for p in second]


def test_a_file_that_will_not_decode_costs_one_source_not_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "good.wav"))
    with open(os.path.join(sources_directory(), "bad.wav"), "w") as fh:
        fh.write("not audio")
    assert len(prepare_all()) == 1


def test_prepare_reports_progress_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    lines = []
    prepare_all(progress=lines.append)
    assert lines


def test_the_night_module_never_imports_prepare():
    """The promise that bedtime is silent: nothing on the playback path may
    reach the module that runs Demucs."""
    import pathlib
    from .import_guard import forbidden_imports
    root = pathlib.Path(__file__).resolve().parent.parent
    forbidden = {"sleepmix.night.prepare", "sleepmix.separation",
                 "sleepmix.separation_process", "sleepmix.analysis",
                 "sleepmix.timestretch"}
    for name in ("plan.py", "palette.py", "stream.py", "player.py",
                 "clock.py", "context.py", "sources.py"):
        offenders = forbidden_imports(
            root / "sleepmix" / "night" / name, root, forbidden)
        assert offenders == set(), f"{name} reaches preparation: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_prepare.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.prepare'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/prepare.py`:

```python
"""The expensive half of the ghost, done whenever it suits you.

Separation takes minutes and spins a laptop's fans up; loop detection and
time-stretching are seconds each. All of it happens here, in a command you run
when you are awake, so that ``sleepmix night`` can start instantly and in
silence. **Nothing on the playback path may import this module** — there is a
test asserting exactly that, because the failure it prevents is a fan running
next to a bed.

What comes out is a ``SourceProfile``: paths, frame counts and frequencies.
What goes in is whatever is in the sources folder.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Callable

from ..analysis import find_loop, slice_loop
from ..audio import load_audio, save_audio, sum_buffers
from ..config import LoopConfig
from ..looping import make_seamless
from ..separation import separate
from ..timestretch import slow_and_pitch
from .pitch import pitch_set
from .sources import (
    SourceProfile, load_profiles, profiles_directory, sources_directory,
    write_profile,
)

# How many loops one song contributes. Enough that a stretch of the night has
# internal variety without any one recurring often. A placeholder.
LOOPS_PER_SOURCE = 3

# Short enough to carry no phrase. Four bars is roughly eight seconds at 120
# BPM, and moves with the detected tempo. A placeholder.
LOOP_BARS = 4

# Slower than played, which pulls gesture below the rate the ear tracks
# phrasing at. A placeholder.
STRETCH_SPEED = 0.6

# A drum kit looping under you at 2 AM is what `sleepmix render`'s shipped
# defaults already turn off by hand.
DROP_STEMS = ("drums",)

_MEDIA_SUFFIXES = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aif", ".aiff")

# Where in the track each loop is looked for, as fractions. Spread out so the
# three loops are genuinely different passages rather than three readings of
# one chorus.
_SEARCH_WINDOWS = ((0.20, 0.40), (0.40, 0.60), (0.60, 0.80))


def source_id_for(path: str) -> str:
    """A stable, filesystem-safe identifier for a source path."""
    stem = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:40]
    digest = hashlib.sha256(os.path.abspath(path).encode()).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else digest


def _kept_stems(stems: dict) -> dict:
    """Everything separation returned except the ones a night does not want.

    Factored out so a test can watch what survives — the drums-dropped rule is
    the one decision here with an audible consequence.
    """
    kept = {k: v for k, v in stems.items() if k not in DROP_STEMS}
    # Separation with no Demucs returns a single `mix` stem; dropping nothing
    # from it is correct, and dropping everything would be silence.
    return kept or dict(stems)


def prepare_source(path: str, sr: int = 44100) -> SourceProfile | None:
    """Separate, loop, stretch and analyse one song. ``None`` if it will not.

    Every failure is one fewer source rather than a raised exception: a
    directory a person drops files into will contain things that are not
    songs, and finding one is ordinary.
    """
    try:
        source_id = source_id_for(path)
        stems = _kept_stems(separate(path))
        reference = sum_buffers(list(stems.values()))

        loop_paths: list[str] = []
        loop_frames: list[int] = []
        analysed = []

        for i, (lo, hi) in enumerate(_SEARCH_WINDOWS[:LOOPS_PER_SOURCE]):
            cfg = LoopConfig(bars=LOOP_BARS, search_start=lo, search_end=hi)
            point = find_loop(reference, cfg)
            raw = slice_loop(reference, point)
            seamless = make_seamless(raw, cfg.crossfade_ms)
            stretched = slow_and_pitch(seamless, STRETCH_SPEED, 0.0)
            if stretched.n_frames <= 0:
                continue

            out = os.path.join(profiles_directory(), f"{source_id}-{i}.wav")
            save_audio(stretched, out)
            loop_paths.append(out)
            loop_frames.append(stretched.n_frames)
            analysed.append(stretched)

        if not loop_paths:
            return None

        # One pooled set per source rather than one per loop: a ghost of *this
        # song* is the more useful object, and the handover preference reasons
        # at song level too.
        pooled = sum_buffers(analysed)
        profile = SourceProfile(
            source_id=source_id,
            loop_paths=tuple(loop_paths),
            loop_frames=tuple(loop_frames),
            pitch_set=pitch_set(pooled),
            sr=analysed[0].sr,
        )
        write_profile(profile)
        return profile
    except Exception:
        return None


def prepare_all(progress: Callable[[str], None] | None = None
                ) -> tuple[SourceProfile, ...]:
    """Prepare everything in the sources folder that is not prepared already.

    Idempotent by design: a source whose profile already exists is skipped, so
    running this again after adding one song costs one song.
    """
    def say(line: str) -> None:
        if progress is not None:
            progress(line)

    try:
        names = sorted(os.path.join(sources_directory(), n)
                       for n in os.listdir(sources_directory())
                       if n.lower().endswith(_MEDIA_SUFFIXES))
    except OSError:
        return ()

    existing = {p.source_id for p in load_profiles()}
    for path in names:
        if source_id_for(path) in existing:
            say(f"already prepared: {os.path.basename(path)}")
            continue
        say(f"preparing: {os.path.basename(path)}")
        if prepare_source(path) is None:
            say(f"  skipped (could not prepare): {os.path.basename(path)}")

    return load_profiles()
```

- [ ] **Step 4: Add the CLI command**

In `sleepmix/cli.py`, add after the `night` command:

```python
@main.command()
def prepare() -> None:
    """Prepare source material for `sleepmix night`.

    Separates, finds loops and analyses everything in the sources folder. This
    is the slow part — minutes per song, with the fans on — and it lives in its
    own command precisely so that it never happens at bedtime.
    """
    from .night.prepare import prepare_all
    from .night.sources import sources_directory

    click.echo(f"Sources: {sources_directory()}")
    profiles = prepare_all(progress=click.echo)
    if not profiles:
        click.echo("Nothing prepared. Drop audio files in the folder above.")
        return
    total = sum(len(p.loop_paths) for p in profiles)
    click.echo(f"Ready: {len(profiles)} source(s), {total} loop(s).")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_prepare.py -q`
Expected: PASS, 13 passed

Then: `pipenv run sleepmix prepare --help`
Expected: the help text above.

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, 574

- [ ] **Step 7: Commit**

```bash
git add sleepmix/night/prepare.py sleepmix/cli.py tests/test_night_prepare.py
git commit -m "feat: the expensive half, done whenever it suits"
```

---

### Task 4: Sources take turns

**Files:**
- Modify: `sleepmix/night/plan.py` (add the schedule; do not touch voice emission yet)
- Modify: `sleepmix/night/context.py` (`NightContext` gains `sources`)
- Test: `tests/test_night_schedule.py`

**Interfaces:**
- Consumes: `night.sources.SourceProfile`, `pitch_distance`; `sleepmix.util.iteration_rng`.
- Produces:
  - `NightContext` gains `sources: tuple[SourceProfile, ...] = ()` — **keyword-defaulted last**, so every existing construction keeps working
  - `Stage` frozen dataclass: `source_index: int`, `start_frame: int`, `end_frame: int`
  - `STAGE_MIN_S = 20 * 60.0`, `STAGE_MAX_S = 45 * 60.0`
  - `schedule_sources(ctx: NightContext, sr: int, night_frames: int) -> tuple[Stage, ...]`
  - `stage_at(schedule: tuple[Stage, ...], frame: int) -> Stage | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_schedule.py`:

```python
"""Who holds the stage, and for how long.

Concurrent voices drawn from different songs would be mud — different keys,
different rooms, different tape — so one source holds the stage at a time.
The handover would be an event, except that the ghosts of the outgoing source
outlive it and cover the seam; that half lives in the planner, and this file
only has to guarantee the schedule it works from is sane and reproducible.
"""
import pytest

from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    STAGE_MAX_S, STAGE_MIN_S, Stage, schedule_sources, stage_at,
)
from sleepmix.night.sources import SourceProfile

SR = 22050
NIGHT_S = 8 * 3600.0


def _profile(name, pitches):
    return SourceProfile(source_id=name, loop_paths=(f"/{name}.wav",),
                         loop_frames=(100000,), pitch_set=tuple(pitches),
                         sr=44100)


def _context(sources=(), seed=1):
    return NightContext(
        seed=seed, night_length_s=NIGHT_S,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0, sources=tuple(sources))


def _schedule(sources, seed=1):
    ctx = _context(sources, seed)
    return schedule_sources(ctx, SR, int(NIGHT_S * SR)), ctx


def test_no_sources_is_an_empty_schedule():
    schedule, _ = _schedule([])
    assert schedule == ()


def test_one_source_holds_the_whole_night():
    schedule, _ = _schedule([_profile("a", (55.0,))])
    assert all(s.source_index == 0 for s in schedule)


def test_the_schedule_covers_the_night_without_gaps_or_overlaps():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abcd")])
    assert schedule[0].start_frame == 0
    for earlier, later in zip(schedule, schedule[1:]):
        assert earlier.end_frame == later.start_frame
    assert schedule[-1].end_frame >= int(NIGHT_S * SR)


def test_every_stage_lasts_a_plausible_stretch():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abcd")])
    for stage in schedule[:-1]:
        seconds = (stage.end_frame - stage.start_frame) / SR
        assert STAGE_MIN_S <= seconds <= STAGE_MAX_S


def test_consecutive_stages_do_not_repeat_a_source_when_others_exist():
    schedule, _ = _schedule([_profile(n, (55.0 + i * 3,))
                             for i, n in enumerate("abcd")])
    for earlier, later in zip(schedule, schedule[1:]):
        assert earlier.source_index != later.source_index


def test_the_next_source_is_the_nearest_in_pitch():
    """The overlap during a handover should be consonant rather than a
    collision, and the planner has the numbers to arrange that."""
    near = _profile("near", (56.0, 84.0))
    far = _profile("far", (78.0, 104.0))
    start = _profile("start", (55.0, 82.5))
    schedule, _ = _schedule([start, near, far])
    first_two = [s.source_index for s in schedule[:2]]
    assert first_two[1] == [start, near, far].index(near) or \
        schedule[0].source_index != 0


def test_the_schedule_is_reproducible_from_the_seed():
    sources = [_profile(n, (55.0 + i,)) for i, n in enumerate("abc")]
    assert _schedule(sources, seed=7)[0] == _schedule(sources, seed=7)[0]


def test_a_different_seed_gives_a_different_schedule():
    sources = [_profile(n, (55.0 + i * 4,)) for i, n in enumerate("abcde")]
    assert _schedule(sources, seed=1)[0] != _schedule(sources, seed=2)[0]


def test_stage_at_finds_the_stage_covering_a_frame():
    schedule, _ = _schedule([_profile(n, (55.0 + i,))
                             for i, n in enumerate("abc")])
    for stage in schedule:
        middle = (stage.start_frame + stage.end_frame) // 2
        assert stage_at(schedule, middle) == stage


def test_stage_at_before_the_night_and_after_it():
    schedule, _ = _schedule([_profile("a", (55.0,))])
    assert stage_at(schedule, -1) is None
    assert stage_at((), 0) is None
    # Past the end clamps to the last stage rather than falling off, so a
    # stream that outlives its own arc keeps its material.
    assert stage_at(schedule, schedule[-1].end_frame + SR) == schedule[-1]


def test_a_source_with_no_pitches_is_still_scheduled():
    """A pitchless source has no ghost, but its loops are still material."""
    schedule, _ = _schedule([_profile("a", ()), _profile("b", (55.0,))])
    assert schedule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_schedule.py -q`
Expected: FAIL — `ImportError: cannot import name 'Stage' from 'sleepmix.night.plan'`

- [ ] **Step 3: Add `sources` to `NightContext`**

In `sleepmix/night/context.py`, import `SourceProfile` from `.sources` and add the field **last, with a default**, so every existing construction keeps working:

```python
    sources: tuple[SourceProfile, ...] = ()
```

Add the same as a keyword-only parameter on `build_context(now, lat_deg, lon_deg, seed, sources=())`, passed straight through. Note in the docstring that profiles are part of the dusk snapshot for the same reason the weather is: what the night is made of should not change while someone is asleep in it.

- [ ] **Step 4: Add the schedule to `plan.py`**

```python
# How long one source holds the stage. Long enough that its several loops get
# to establish a place, short enough that a night visits more than one or two
# of them. Both are placeholders.
STAGE_MIN_S = 20 * 60.0
STAGE_MAX_S = 45 * 60.0


@dataclass(frozen=True)
class Stage:
    """One source holding the stage, over a span of the night."""

    source_index: int
    start_frame: int
    end_frame: int


def schedule_sources(ctx: NightContext, sr: int,
                     night_frames: int) -> tuple[Stage, ...]:
    """Who holds the stage, when, for the whole night.

    Sources take turns rather than sounding together: concurrent voices drawn
    from different songs would be mud, since they share neither key nor room
    nor tape. Handing over would be an event, except that the outgoing
    source's ghosts outlive it and cover the seam — which is why this function
    only has to decide *who and when*, and never has to soften anything.

    The next source is chosen as the nearest in pitch among those not just
    used, so the overlap during a handover is consonant. With one source the
    rule is inert; with none there is no schedule at all.
    """
    if not ctx.sources:
        return ()

    stages: list[Stage] = []
    cursor = 0
    step = 0
    current = int(iteration_rng(ctx.seed, "night:stage", 0)
                  .integers(0, len(ctx.sources)))

    while cursor < night_frames:
        rng = iteration_rng(ctx.seed, "night:stage", step + 1)
        length = int(float(rng.uniform(STAGE_MIN_S, STAGE_MAX_S)) * sr)
        stages.append(Stage(source_index=current, start_frame=cursor,
                            end_frame=cursor + length))
        cursor += length
        step += 1

        if len(ctx.sources) > 1:
            candidates = [i for i in range(len(ctx.sources)) if i != current]
            current = min(candidates, key=lambda i: (
                pitch_distance(ctx.sources[current], ctx.sources[i]), i))

    return tuple(stages)


def stage_at(schedule: tuple[Stage, ...], frame: int) -> Stage | None:
    """The stage covering ``frame``, or ``None``.

    Past the end clamps to the last stage rather than falling off, so a stream
    that outlives its own arc keeps its material instead of going synthetic.
    """
    if not schedule or frame < 0:
        return None
    for stage in schedule:
        if stage.start_frame <= frame < stage.end_frame:
            return stage
    return schedule[-1] if frame >= schedule[-1].end_frame else None
```

Note the deterministic tie-break (`, i`) in the `min` key — without it, two candidates at equal pitch distance resolve by dict order and the schedule stops being reproducible.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_schedule.py tests/test_night_context.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, 585 — and confirm `test_plan_module_imports_no_audio` still passes, since `plan.py` now imports `sources.py`.

- [ ] **Step 7: Commit**

```bash
git add sleepmix/night/plan.py sleepmix/night/context.py tests/test_night_schedule.py
git commit -m "feat: sources take turns, and the next one is chosen to be close"
```

---

### Task 5: The pair — a source voice and its ghost

**Files:**
- Modify: `sleepmix/night/plan.py`
- Test: `tests/test_night_ghost.py`; update `tests/test_night_plan.py` where the `Voice` shape or `TEXTURES` is asserted

**Interfaces:**
- Produces:
  - `Voice` gains `source_id: str | None = None`, `loop_index: int = 0`, `gain: float = 1.0`
  - `TEXTURES = ("drone", "noiseband", "source")`
  - `MAX_SOURCE_RATIO = 0.85`, `MIN_AUDIBLE_RATIO = 0.05`
  - `HANDOVER_COVER_S = 90.0`, `OUTLIVE_CHANCE = 0.15`, `OUTLIVE_MIN`/`OUTLIVE_MAX = 1.5 / 2.5`
  - `source_ratio(elapsed: float) -> float`
  - `is_ghost(voice: Voice) -> bool`

**Two rules that keep the walk deterministic. Both are easy to break and neither fails loudly.**

1. **Every walk step consumes exactly two voice indices** — `index` for the primary voice and `index + 1` for its ghost — whether or not both are emitted. The step's own RNG stays keyed on `index`. Advancing by a variable amount would move every later voice depending on which branch a step took.
2. **Every draw happens on every step, before any branch.** Draw the lifetime, the interval, the texture pick, the loop pick, the ghost-pitch pick, the outlive roll and the gap *unconditionally*, then use what the branch needs. A draw made inside an `if` desynchronises the stream, and the symptom is that a night is reproducible until you change the sources folder and then silently is not.

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_ghost.py`:

```python
"""The pair, and the two things one mechanism buys.

A ghost is its own Voice rather than a mode of one. That single choice gives
the birth ratio (the relative gain of a co-located pair) and ghosts that
outlive their source (the same pair with different lifetimes) without a second
mechanism for either.
"""
import pytest

from sleepmix.night.clock import arc_at
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    MAX_SOURCE_RATIO, MIN_AUDIBLE_RATIO, TEXTURES, is_ghost, plan_voices,
    schedule_sources, source_ratio, stage_at,
)
from sleepmix.night.sources import SourceProfile

SR = 22050
NIGHT_S = 8 * 3600.0


def _profile(name, pitches=(55.0, 82.5)):
    return SourceProfile(source_id=name, loop_paths=(f"/{name}-0.wav",
                                                     f"/{name}-1.wav"),
                         loop_frames=(120000, 130000), pitch_set=tuple(pitches),
                         sr=44100)


def _context(sources=(), seed=1):
    return NightContext(
        seed=seed, night_length_s=NIGHT_S,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0, sources=tuple(sources))


def _night(ctx):
    return plan_voices(ctx, SR, 0, int(ctx.night_length_s * SR))


# -- the ratio ---------------------------------------------------------
def test_the_ratio_never_reaches_one():
    """You never hear the unprocessed loop alone, at any hour."""
    for i in range(101):
        assert source_ratio(i / 100.0) <= MAX_SOURCE_RATIO < 1.0


def test_the_ratio_falls_across_the_night():
    assert source_ratio(0.0) > source_ratio(0.5) > source_ratio(1.0)


def test_the_ratio_is_monotone():
    values = [source_ratio(i / 200.0) for i in range(201)]
    assert all(b <= a + 1e-9 for a, b in zip(values, values[1:]))


def test_the_ratio_clamps_outside_the_night():
    assert source_ratio(-1.0) == source_ratio(0.0)
    assert source_ratio(5.0) == source_ratio(1.0)


# -- with no sources ---------------------------------------------------
def test_with_no_sources_nothing_names_a_source():
    for voice in _night(_context()):
        assert voice.source_id is None
        assert voice.texture in ("drone", "noiseband")


def test_with_no_sources_the_plan_is_unchanged_from_phase_one():
    """The strongest available statement that this phase is additive."""
    ctx = _context()
    assert _night(ctx) == _night(_context())


# -- with sources ------------------------------------------------------
def test_early_voices_are_mostly_source_and_late_ones_are_ghosts():
    ctx = _context([_profile("a")])
    voices = _night(ctx)
    half = int(NIGHT_S * SR / 2)
    early = [v for v in voices if v.birth_frame < half]
    late = [v for v in voices if v.birth_frame >= half]
    early_source = sum(1 for v in early if v.texture == "source")
    late_source = sum(1 for v in late if v.texture == "source")
    assert early_source > 0
    assert late_source < early_source


def test_a_source_voice_names_a_real_loop_of_its_profile():
    ctx = _context([_profile("a")])
    for voice in _night(ctx):
        if voice.texture == "source":
            assert voice.source_id == "a"
            assert 0 <= voice.loop_index < len(_profile("a").loop_paths)


def test_a_ghost_sounds_at_a_pitch_from_its_source(): 
    ctx = _context([_profile("a", (55.0, 82.5))])
    ghosts = [v for v in _night(ctx) if is_ghost(v)]
    assert ghosts
    for ghost in ghosts:
        # The root descends across the night, so allow for that rather than
        # demanding an exact member of the set.
        assert 20.0 < ghost.pitch_hz < 130.0


def test_a_source_voice_and_its_ghost_are_born_together():
    ctx = _context([_profile("a")])
    voices = {v.index: v for v in _night(ctx)}
    for voice in voices.values():
        if voice.texture == "source":
            ghost = voices.get(voice.index + 1)
            if ghost is not None:
                assert ghost.birth_frame == voice.birth_frame
                assert ghost.source_id == voice.source_id


def test_the_pair_is_equal_power():
    ctx = _context([_profile("a")])
    voices = {v.index: v for v in _night(ctx)}
    for voice in voices.values():
        if voice.texture != "source":
            continue
        ghost = voices.get(voice.index + 1)
        if ghost is None:
            continue
        assert voice.gain ** 2 + ghost.gain ** 2 == pytest.approx(1.0, abs=1e-6)


def test_no_voice_is_ever_born_above_the_ceiling_at_its_birth():
    """The nested-clocks rule still holds for source voices."""
    ctx = _context([_profile("a")])
    for voice in _night(ctx):
        arc = arc_at(voice.birth_frame / SR, ctx)
        assert voice.decay.lowpass_end_hz <= arc.brightness_hz + 1e-6
        assert voice.decay.amp_end_db <= arc.level_db + 1e-9


def test_a_pitchless_source_still_produces_source_voices():
    ctx = _context([_profile("a", ())])
    voices = _night(ctx)
    assert any(v.texture == "source" for v in voices)
    assert not any(is_ghost(v) for v in voices)


# -- outliving ---------------------------------------------------------
def test_every_handover_is_covered_by_a_ghost():
    """The seam between two sources is hidden by the mechanism already
    chosen, not by a crossfade added for the purpose."""
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abc")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    voices = _night(ctx)
    for stage in schedule[:-1]:
        crossing = [v for v in voices
                    if is_ghost(v)
                    and v.birth_frame < stage.end_frame
                    and v.birth_frame + v.n_frames > stage.end_frame]
        assert crossing, f"handover at {stage.end_frame} is bare"


def test_some_ghosts_outlive_their_source_away_from_a_handover():
    ctx = _context([_profile("a")])
    voices = {v.index: v for v in _night(ctx)}
    outliving = 0
    for voice in voices.values():
        if voice.texture != "source":
            continue
        ghost = voices.get(voice.index + 1)
        if ghost is not None and (ghost.birth_frame + ghost.n_frames >
                                  voice.birth_frame + voice.n_frames):
            outliving += 1
    assert outliving > 0


def test_outliving_is_the_exception_not_the_rule():
    """A repeated gesture is the failure mode this design worries about
    most, so most pairs must die together."""
    ctx = _context([_profile("a")])
    voices = {v.index: v for v in _night(ctx)}
    pairs, outliving = 0, 0
    for voice in voices.values():
        if voice.texture != "source":
            continue
        ghost = voices.get(voice.index + 1)
        if ghost is None:
            continue
        pairs += 1
        if (ghost.birth_frame + ghost.n_frames >
                voice.birth_frame + voice.n_frames + SR):
            outliving += 1
    assert pairs > 10
    assert outliving < pairs * 0.6


# -- the invariants ----------------------------------------------------
def test_a_window_still_matches_the_whole_night_restricted_to_it():
    """The property block independence rests on, with sources in play."""
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abc")])
    start, end = 3000 * SR, 3010 * SR
    windowed = plan_voices(ctx, SR, start, end)
    expected = [v for v in _night(ctx)
                if v.birth_frame < end and v.birth_frame + v.n_frames > start]
    assert windowed == expected


def test_a_window_across_a_handover_matches_too():
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abc")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    seam = schedule[0].end_frame
    windowed = plan_voices(ctx, SR, seam - 5 * SR, seam + 5 * SR)
    expected = [v for v in _night(ctx)
                if v.birth_frame < seam + 5 * SR
                and v.birth_frame + v.n_frames > seam - 5 * SR]
    assert windowed == expected


def test_voice_indices_stay_unique_with_pairs_in_play():
    ctx = _context([_profile("a")])
    indices = [v.index for v in _night(ctx)]
    assert len(indices) == len(set(indices))


def test_every_texture_is_one_the_palette_can_render():
    ctx = _context([_profile("a")])
    assert {v.texture for v in _night(ctx)} <= set(TEXTURES)


def test_the_plan_is_still_reproducible_from_seed_and_context():
    ctx = _context([_profile("a")])
    assert _night(ctx) == _night(_context([_profile("a")]))


def test_planning_a_whole_night_with_sources_is_still_fast():
    import time
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abcd")])
    began = time.perf_counter()
    _night(ctx)
    assert time.perf_counter() - began < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_ghost.py -q`
Expected: FAIL — `ImportError: cannot import name 'source_ratio'`

- [ ] **Step 3: Extend `Voice` and the constants**

In `sleepmix/night/plan.py`:

```python
TEXTURES = ("drone", "noiseband", "source")

# The most source-derived voice of the night still carries some of its own
# ghost, so the unprocessed loop is never heard alone at any hour. This is the
# most direct implementation of "clearly music, not identifiable", and it is a
# placeholder nobody has listened to.
MAX_SOURCE_RATIO = 0.85

# Below this a voice in the pair is not worth rendering.
MIN_AUDIBLE_RATIO = 0.05

# A ghost crossing a handover must reach at least this far past it, so the
# seam between two sources is never bare.
HANDOVER_COVER_S = 90.0

# Away from a handover, a ghost outliving its source is a flourish rather than
# the rule — a repeated gesture is the failure mode this design worries about
# most. All three are placeholders.
OUTLIVE_CHANCE = 0.15
OUTLIVE_MIN, OUTLIVE_MAX = 1.5, 2.5
```

Add three fields to `Voice`, **last and keyword-defaulted**, so every existing construction and every existing test keeps working:

```python
    source_id: str | None = None
    loop_index: int = 0
    gain: float = 1.0
```

Extend the `Voice` docstring: a voice now names *what it is made of* — a synthesized texture, or a loop belonging to a prepared source. `gain` is the pair balance and applies to every voice; `source_id` on a non-`"source"` texture means *this is the ghost of that source*, which is what `is_ghost` reads.

```python
def is_ghost(voice: Voice) -> bool:
    """True for a voice synthesized from a source's own spectrum.

    A ghost is not a separate generator — it is a drone or a noise band whose
    pitch came from a `SourceProfile` rather than from the seed. What makes it
    a ghost is the provenance, which is why this is a function rather than a
    texture.
    """
    return voice.source_id is not None and voice.texture != "source"


def source_ratio(elapsed: float) -> float:
    """How much of a pair born at ``elapsed`` is the loop rather than its ghost.

    Linear rather than the arc's own eased curve: the arc descends fast and
    lingers, which is right for level and wrong here — a source that vanished
    in the first hour would make "source-derived early" a technicality. A
    placeholder either way.
    """
    return lerp(MAX_SOURCE_RATIO, 0.0, min(max(elapsed, 0.0), 1.0))
```

- [ ] **Step 4: Rewrite `plan_voices`' walk**

Replace the body of the walk loop. The whole of the change is: draw everything first, then branch.

```python
    schedule = schedule_sources(ctx, sr, night_frames)

    while cursor < to_frame:
        rng = iteration_rng(ctx.seed, "night:voice", index)
        t_s = cursor / sr
        arc = arc_at(t_s, ctx)
        elapsed = min(max(cursor / night_frames, 0.0), 1.0)

        # Every draw happens on every step, before any branch. A draw made
        # inside an `if` desynchronises the walk, and the symptom is a night
        # that is reproducible until the sources folder changes.
        lifetime_s = float(rng.uniform(MIN_VOICE_S, MAX_VOICE_S))
        cents = int(rng.choice(intervals))
        synth_texture = str(rng.choice(TEXTURES[:2]))
        loop_pick = int(rng.integers(0, 1024))
        pitch_pick = int(rng.integers(0, 1024))
        outlive_roll = float(rng.random())
        outlive_factor = float(rng.uniform(OUTLIVE_MIN, OUTLIVE_MAX))
        gap_s = _birth_gap_s(arc.density, rng)

        n_frames = int(lifetime_s * sr)
        descent = -ROOT_DESCENT_SEMITONES * elapsed * 100.0
        decay = _decay_for(arc, base_decay)
        stage = stage_at(schedule, cursor)
        emitted: list[Voice] = []

        if stage is None:
            emitted.append(Voice(
                index=index, birth_frame=cursor, n_frames=n_frames,
                pitch_hz=_pitch_hz(root_hz, cents + descent),
                texture=synth_texture, decay=decay))
        else:
            profile = ctx.sources[stage.source_index]
            ratio = source_ratio(elapsed)
            source_gain = math.sqrt(ratio)
            ghost_gain = math.sqrt(1.0 - ratio)

            if ratio > MIN_AUDIBLE_RATIO:
                emitted.append(Voice(
                    index=index, birth_frame=cursor, n_frames=n_frames,
                    pitch_hz=0.0, texture="source", decay=decay,
                    source_id=profile.source_id,
                    loop_index=loop_pick % len(profile.loop_paths),
                    gain=source_gain))

            if profile.pitch_set and (1.0 - ratio) > MIN_AUDIBLE_RATIO:
                ghost_frames = n_frames
                # Systematically at a handover: reach past the seam so it is
                # never bare. Occasionally elsewhere: a flourish.
                seam = stage.end_frame
                if cursor < seam <= cursor + n_frames + int(HANDOVER_COVER_S * sr):
                    ghost_frames = max(
                        ghost_frames,
                        seam - cursor + int(HANDOVER_COVER_S * sr))
                elif outlive_roll < OUTLIVE_CHANCE:
                    ghost_frames = int(ghost_frames * outlive_factor)
                ghost_frames = min(ghost_frames, int(MAX_VOICE_S * sr * 3))

                base_hz = profile.pitch_set[pitch_pick % len(profile.pitch_set)]
                emitted.append(Voice(
                    index=index + 1, birth_frame=cursor,
                    n_frames=ghost_frames,
                    pitch_hz=_pitch_hz(base_hz, descent),
                    texture=synth_texture, decay=decay,
                    source_id=profile.source_id, gain=ghost_gain))

            if not emitted:
                # A pitchless source at the far end of the night has neither
                # half left. Fall back rather than emitting silence.
                emitted.append(Voice(
                    index=index, birth_frame=cursor, n_frames=n_frames,
                    pitch_hz=_pitch_hz(root_hz, cents + descent),
                    texture=synth_texture, decay=decay))

        for voice in emitted:
            if voice.birth_frame < to_frame and (
                    voice.birth_frame + voice.n_frames > from_frame):
                voices.append(voice)

        cursor += max(int(gap_s * sr), 1)
        index += 2      # a pair's worth, whether or not both were emitted
```

Add `import math` at the top of the module — it imports no audio and does not affect the guard.

`voices` must be sorted by `birth_frame` before returning if any existing test depends on ordering; a pair shares a birth frame, so sort with `index` as the tie-break to keep it stable.

- [ ] **Step 5: Update the existing plan tests**

`tests/test_night_plan.py` asserts `TEXTURES` membership and voice-index uniqueness. Both still hold. Its `test_a_night_produces_voices` and lifetime-bound tests construct no sources, so they take the `stage is None` path unchanged. Run them and fix only what genuinely moved — an assertion that breaks here is a real behaviour change and should be reported, not adjusted away.

- [ ] **Step 6: Run tests**

Run: `pipenv run pytest tests/test_night_ghost.py tests/test_night_plan.py tests/test_night_schedule.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `pipenv run pytest -q`
Expected: PASS, ~608

- [ ] **Step 8: Commit**

```bash
git add sleepmix/night/plan.py tests/test_night_ghost.py tests/test_night_plan.py
git commit -m "feat: a voice, and the ghost born beside it"
```

---

### Task 6: The palette plays a prepared loop

**Files:**
- Modify: `sleepmix/night/palette.py`
- Test: `tests/test_night_palette.py` (additions)

**Interfaces:**
- Consumes: `sleepmix.audio.load_audio`; `night.sources.SourceProfile`.
- Produces:
  - `render_voice(voice, sr, seed, profiles=())` — new optional last parameter, a tuple of `SourceProfile`
  - `_LOOP_CACHE_BYTES = 128 * 1024 * 1024`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_night_palette.py`:

```python
# -- source voices -----------------------------------------------------

def _loop_file(tmp_path, seconds=2.0, freq=220.0, sr=SR):
    import soundfile as sf
    t = np.arange(int(seconds * sr)) / sr
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    path = tmp_path / f"loop-{freq}.wav"
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return str(path), int(seconds * sr)


def _source_voice(profile, seconds=30.0, gain=1.0, index=0):
    return Voice(index=index, birth_frame=0, n_frames=int(seconds * SR),
                 pitch_hz=0.0, texture="source", decay=StemDecayConfig(),
                 source_id=profile.source_id, loop_index=0, gain=gain)


def _profile(tmp_path, **kw):
    from sleepmix.night.sources import SourceProfile
    path, frames = _loop_file(tmp_path, **kw)
    return SourceProfile(source_id="a", loop_paths=(path,),
                         loop_frames=(frames,), pitch_set=(55.0,), sr=SR)


def test_a_source_voice_is_the_length_it_says_it_is(tmp_path):
    profile = _profile(tmp_path)
    buf = render_voice(_source_voice(profile), SR, seed=1, profiles=(profile,))
    assert buf.n_frames == int(30.0 * SR)
    assert buf.n_channels == 2


def test_a_source_voice_tiles_a_short_loop_to_fill_its_life(tmp_path):
    profile = _profile(tmp_path, seconds=2.0)
    buf = render_voice(_source_voice(profile, seconds=10.0), SR, seed=1,
                       profiles=(profile,))
    x = np.abs(buf.data).max(axis=1)
    middle = x[3 * SR: 7 * SR]
    assert middle.max() > 1e-3          # still sounding well past one loop


def test_a_source_voice_has_no_attack_or_release(tmp_path):
    profile = _profile(tmp_path)
    buf = render_voice(_source_voice(profile), SR, seed=1, profiles=(profile,))
    x = np.abs(buf.data).max(axis=1)
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert x[:int(0.05 * SR)].max() < middle * 0.05
    assert x[-int(0.05 * SR):].max() < middle * 0.05


def test_gain_actually_scales_a_source_voice(tmp_path):
    profile = _profile(tmp_path)
    loud = render_voice(_source_voice(profile, gain=1.0), SR, 1, (profile,))
    quiet = render_voice(_source_voice(profile, gain=0.25), SR, 1, (profile,))
    assert np.abs(quiet.data).max() < np.abs(loud.data).max() * 0.5


def test_gain_scales_a_synthesized_voice_too(tmp_path):
    loud = _voice("drone")
    quiet = Voice(index=0, birth_frame=0, n_frames=loud.n_frames,
                  pitch_hz=loud.pitch_hz, texture="drone",
                  decay=StemDecayConfig(), gain=0.25)
    assert np.abs(render_voice(quiet, SR, 1).data).max() < \
        np.abs(render_voice(loud, SR, 1).data).max() * 0.5


def test_a_source_voice_with_no_matching_profile_is_silence_not_a_raise(tmp_path):
    profile = _profile(tmp_path)
    orphan = _source_voice(profile)
    buf = render_voice(orphan, SR, seed=1, profiles=())
    assert buf.n_frames == orphan.n_frames
    assert np.all(buf.data == 0.0)


def test_a_source_voice_whose_loop_file_has_gone_is_silence(tmp_path):
    from sleepmix.night.sources import SourceProfile
    profile = SourceProfile(source_id="a", loop_paths=("/nowhere/gone.wav",),
                            loop_frames=(1000,), pitch_set=(55.0,), sr=SR)
    buf = render_voice(_source_voice(profile), SR, 1, (profile,))
    assert np.all(buf.data == 0.0)


def test_an_out_of_range_loop_index_is_silence_not_a_raise(tmp_path):
    profile = _profile(tmp_path)
    voice = Voice(index=0, birth_frame=0, n_frames=SR, pitch_hz=0.0,
                  texture="source", decay=StemDecayConfig(),
                  source_id="a", loop_index=99, gain=1.0)
    assert np.all(render_voice(voice, SR, 1, (profile,)).data == 0.0)


def test_a_source_voice_is_reproducible(tmp_path):
    profile = _profile(tmp_path)
    a = render_voice(_source_voice(profile), SR, 5, (profile,))
    b = render_voice(_source_voice(profile), SR, 5, (profile,))
    assert np.array_equal(a.data, b.data)


def test_a_source_voice_is_resampled_when_the_loop_rate_differs(tmp_path):
    profile = _profile(tmp_path)
    buf = render_voice(_source_voice(profile), 44100, 1, (profile,))
    assert buf.sr == 44100
    assert buf.n_frames == int(30.0 * 44100)
```

- [ ] **Step 2: Run to verify failure**

Run: `pipenv run pytest tests/test_night_palette.py -q`
Expected: FAIL — `render_voice() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Implement**

In `sleepmix/night/palette.py`, add a bounded loop cache and the source branch:

```python
# Prepared loops are small — seconds each — but a night asks for one several
# times a minute for eight hours. Bounded by bytes for the same reason
# `stream.py`'s voice cache is: a count is not a memory budget.
_LOOP_CACHE_BYTES = 128 * 1024 * 1024
_loop_cache: "OrderedDict[tuple[str, int], AudioBuffer]" = OrderedDict()
_loop_cache_bytes = 0


def _loop_for(path: str, sr: int) -> AudioBuffer | None:
    """A prepared loop at ``sr``, or ``None`` if it cannot be read.

    The cache is an optimisation and never an input: evicting it changes
    nothing about what comes out, which is what keeps block independence true.
    """
    global _loop_cache_bytes
    key = (path, sr)
    hit = _loop_cache.get(key)
    if hit is not None:
        _loop_cache.move_to_end(key)
        return hit
    try:
        buf = load_audio(path, sr=sr).to_stereo()
    except Exception:
        return None
    if buf.n_frames <= 0:
        return None

    _loop_cache[key] = buf
    _loop_cache_bytes += buf.data.nbytes
    while len(_loop_cache) > 1 and _loop_cache_bytes > _LOOP_CACHE_BYTES:
        _, evicted = _loop_cache.popitem(last=False)
        _loop_cache_bytes -= evicted.data.nbytes
    return buf


def _source(voice: Voice, n: int, sr: int,
            profiles: tuple[SourceProfile, ...]) -> np.ndarray | None:
    """A prepared loop, tiled to ``n`` frames. ``None`` if unavailable.

    Every way this can fail — no matching profile, an index past the end, a
    file that has moved since `prepare` ran — costs this voice and nothing
    else. A person moves folders, and a night should survive it.
    """
    profile = next((p for p in profiles if p.source_id == voice.source_id),
                   None)
    if profile is None:
        return None
    if not (0 <= voice.loop_index < len(profile.loop_paths)):
        return None
    loop = _loop_for(profile.loop_paths[voice.loop_index], sr)
    if loop is None:
        return None

    reps = int(np.ceil(n / loop.n_frames))
    tiled = np.tile(loop.data, (reps, 1))[:n]
    assert len(tiled) == n
    return tiled.astype(np.float32)
```

Then in `render_voice`, add the parameter and the branch, and apply `voice.gain` alongside `_PEAK`:

```python
def render_voice(voice: Voice, sr: int, seed: int,
                 profiles: tuple[SourceProfile, ...] = ()) -> AudioBuffer:
    n = max(voice.n_frames, 1)
    rng = iteration_rng(seed, voice.key, 0)

    if voice.texture == "source":
        stereo = _source(voice, n, sr, profiles)
        if stereo is None:
            return AudioBuffer(np.zeros((n, 2), dtype=np.float32), sr)
    elif voice.texture in ("drone", "noiseband"):
        generate = _drone if voice.texture == "drone" else _noise_band
        left = generate(n, sr, voice.pitch_hz, rng)
        right = generate(n, sr, voice.pitch_hz, rng)
        stereo = np.stack([left, right], axis=1)
    else:
        raise ValueError(f"unknown texture: {voice.texture!r}")

    peak = float(np.abs(stereo).max())
    if peak > 0:
        stereo = stereo * (_PEAK * voice.gain / peak)
    stereo *= fade_envelope(n, sr)[:, None]
    return AudioBuffer(stereo.astype(np.float32), sr)
```

Note the tiling assertion — it is there because off-by-one in a tile is the third named hazard and it fails silently otherwise.

- [ ] **Step 4: Run tests**

Run: `pipenv run pytest tests/test_night_palette.py -q`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `pipenv run pytest -q`
Expected: PASS, ~618

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/palette.py tests/test_night_palette.py
git commit -m "feat: the palette plays what was prepared"
```

---

### Task 7: Wiring, and the invariant re-proved with sources in play

**Files:**
- Modify: `sleepmix/night/stream.py` (pass profiles through to the palette)
- Modify: `sleepmix/cli.py` (`night` loads profiles and says which mode it is in)
- Test: `tests/test_night_stream.py` (additions), `tests/test_cli.py` (additions)

**Interfaces:**
- `NightStream` needs no new constructor argument — profiles ride on `ctx`.
- `night` prints one extra line naming how many sources are in play, or that it is running on synthesis alone.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_night_stream.py`:

```python
# -- sources in play ---------------------------------------------------

def _source_context(tmp_path, seed=3, n_sources=2):
    """A context with real, loadable prepared loops."""
    import soundfile as sf
    from sleepmix.night.sources import SourceProfile
    profiles = []
    for i in range(n_sources):
        t = np.arange(int(3.0 * SR)) / SR
        y = (0.4 * np.sin(2 * np.pi * (110.0 + 30 * i) * t)).astype(np.float32)
        path = tmp_path / f"loop-{i}.wav"
        sf.write(str(path), np.stack([y, y], axis=1), SR)
        profiles.append(SourceProfile(
            source_id=f"s{i}", loop_paths=(str(path),),
            loop_frames=(len(y),), pitch_set=(55.0 + 4 * i,), sr=SR))
    ctx = _context(seed=seed)
    return replace(ctx, sources=tuple(profiles))


def test_a_block_with_sources_is_the_right_shape(tmp_path):
    stream = NightStream(_source_context(tmp_path), sr=SR)
    block = stream.block(6)
    assert block.n_frames == int(BLOCK_S * SR)
    assert block.n_channels == 2


def test_source_material_actually_reaches_the_audio(tmp_path):
    """The whole point: a night with sources must not sound like a night
    without them."""
    with_sources = NightStream(_source_context(tmp_path), sr=SR).block(6)
    without = NightStream(_context(seed=3), sr=SR).block(6)
    assert not np.array_equal(with_sources.data, without.data)


def test_block_independence_holds_with_sources(tmp_path):
    ctx = _source_context(tmp_path)
    alone = NightStream(ctx, sr=SR).block(37)
    sequential = NightStream(ctx, sr=SR)
    for index in range(38):
        produced = sequential.block(index)
    assert np.array_equal(alone.data, produced.data)


def test_block_independence_holds_across_a_handover(tmp_path):
    """The seam between two sources is the one place composition could
    reintroduce an order dependency."""
    from sleepmix.night.plan import schedule_sources
    ctx = _source_context(tmp_path, n_sources=3)
    schedule = schedule_sources(ctx, SR, int(ctx.night_length_s * SR))
    seam_block = schedule[0].end_frame // int(BLOCK_S * SR)
    alone = NightStream(ctx, sr=SR).block(seam_block)
    again = NightStream(ctx, sr=SR).block(seam_block)
    assert np.array_equal(alone.data, again.data)


def test_blocks_with_sources_render_in_any_order(tmp_path):
    """Stronger than alone-versus-sequence: defeats any eviction-order or
    accumulation effect in either cache."""
    ctx = _source_context(tmp_path)
    reference = {i: NightStream(ctx, sr=SR).block(i).data for i in range(0, 40, 7)}
    shuffled = NightStream(ctx, sr=SR)
    for index in [35, 0, 21, 7, 28, 14]:
        assert np.array_equal(shuffled.block(index).data, reference[index])


def test_an_empty_sources_tuple_is_bit_identical_to_phase_one():
    """The strongest available statement that this phase is additive."""
    ctx = _context(seed=3)
    with_field = replace(ctx, sources=())
    assert np.array_equal(NightStream(ctx, sr=SR).block(11).data,
                          NightStream(with_field, sr=SR).block(11).data)


def test_a_profile_whose_loop_has_gone_costs_its_voice_not_the_block(tmp_path):
    from sleepmix.night.sources import SourceProfile
    ctx = _source_context(tmp_path)
    broken = replace(ctx, sources=(SourceProfile(
        source_id=ctx.sources[0].source_id, loop_paths=("/gone/x.wav",),
        loop_frames=(1000,), pitch_set=(55.0,), sr=SR),))
    block = NightStream(broken, sr=SR).block(6)
    assert block.n_frames == int(BLOCK_S * SR)
    assert np.all(np.isfinite(block.data))


def test_nothing_clips_with_sources(tmp_path):
    stream = NightStream(_source_context(tmp_path), sr=SR)
    for index in (0, 6, 60, 600):
        assert np.abs(stream.summed(index)).max() <= 1.0
```

Add `from dataclasses import replace` to that file's imports.

Append to `tests/test_cli.py`:

```python
def test_night_says_it_is_running_on_synthesis_when_nothing_is_prepared(
        tmp_path, monkeypatch, _fake_device, _no_network):
    """A person who has not run `prepare` should be told, not left guessing
    why it sounds the same as yesterday."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(main, ["night", "--seconds", "1"])
    assert "synthesis" in result.output.lower()


def test_night_names_the_sources_it_found(
        tmp_path, monkeypatch, _fake_device, _no_network):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    from sleepmix.night.sources import SourceProfile, write_profile
    write_profile(SourceProfile(source_id="a", loop_paths=("/a.wav",),
                                loop_frames=(1000,), pitch_set=(55.0,),
                                sr=44100))
    result = CliRunner().invoke(main, ["night", "--seconds", "1"])
    assert "1 source" in result.output
```

Use the existing `_fake_device` fixture in that file — a `sounddevice` stand-in that opens without hardware and swallows writes — together with `_no_network`, rather than writing new helpers. Both already exist.

**Do not reach for a helper that forces the import to fail.** Phase 1's final dispatch deliberately moved the `sounddevice` check above every `click.echo`, so a user without the extra reads an error rather than three lines of encouragement first. That means the mode line prints after the check and is invisible to a test that makes the import raise. `_fake_device` lets the command run far enough to print it without hardware, which is why it is there. Undoing a fix to make a test easier is how the fix stops being a fix — say so in the test's docstring.

- [ ] **Step 2: Run to verify failure**

Run: `pipenv run pytest tests/test_night_stream.py tests/test_cli.py -q`
Expected: FAIL — `NightContext` has no field `sources` in `replace`, or the mode line is absent.

- [ ] **Step 3: Pass profiles through the stream**

In `sleepmix/night/stream.py`, `_rendered` currently calls `render_voice(voice, self.sr, self.ctx.seed)`. Change it to pass the profiles:

```python
        raw = render_voice(voice, self.sr, self.ctx.seed, self.ctx.sources)
```

Add to `NightStream`'s class docstring: profiles arrive on the context rather than as a constructor argument, so `block(i)` stays a pure function of `(ctx, sr, block_s, i)` and the independence argument needs no amendment.

- [ ] **Step 4: Wire the CLI**

In `cli.py`'s `night` command, after the `sounddevice` check and before building the context:

```python
    from .night.sources import load_profiles, sources_directory

    profiles = load_profiles()
    ctx = build_context(dt.datetime.now(dt.timezone.utc), lat, lon, seed,
                        sources=profiles)
    ...
    if profiles:
        loops = sum(len(p.loop_paths) for p in profiles)
        click.echo(f"Material: {len(profiles)} source(s), {loops} loop(s).")
    else:
        click.echo(f"Material: synthesis only — nothing prepared yet. "
                   f"Drop audio in {sources_directory()} and run "
                   f"`sleepmix prepare`.")
```

- [ ] **Step 5: Run tests**

Run: `pipenv run pytest tests/test_night_stream.py tests/test_cli.py tests/test_night_ghost.py -q`
Expected: PASS

- [ ] **Step 6: Render the listening excerpts**

This is where the phase becomes audible. Prepare one real song first, then render.

```bash
pipenv run python - <<'PY'
from dataclasses import replace
from datetime import datetime, timezone
import numpy as np
from sleepmix.audio import save_audio, AudioBuffer
from sleepmix.night.context import build_context
from sleepmix.night.sources import load_profiles
from sleepmix.night.stream import NightStream, BLOCK_S

ctx = build_context(datetime(2026, 12, 21, 22, 30, tzinfo=timezone.utc),
                    52.3676, 4.9041, seed=1, sources=load_profiles())
print(f"{len(ctx.sources)} source(s)")
stream = NightStream(ctx, sr=44100)
for label, hour in [("2230", 0.0), ("0100", 2.5), ("0400", 5.5)]:
    first = int(hour * 3600 / BLOCK_S)
    blocks = [stream.block(first + i).data for i in range(18)]
    save_audio(AudioBuffer(np.concatenate(blocks), 44100), f"night-{label}.wav")
    print(f"wrote night-{label}.wav")
PY
```

Report RMS, peak, spectral centroid, voice count, and the fraction that is source-derived versus ghost, per excerpt. **Measurements only — offer no judgement about how it sounds.** The listening belongs to the operator, and every taste value in this phase is unvalidated.

- [ ] **Step 7: Full suite**

Run: `pipenv run pytest -q`
Expected: PASS, ~628

- [ ] **Step 8: Commit**

```bash
git add sleepmix/night/stream.py sleepmix/cli.py tests/test_night_stream.py tests/test_cli.py
git commit -m "feat: the night finds what was prepared, and says so"
```

---

### Task 8: The documentation this project runs on

**Files:**
- Modify: `docs/architecture.md`, `docs/project-state.md`, `README.md`

This task writes no application code. If you find a code defect, report it rather than fixing it.

**Read first, in full:** the spec, both docs, and this plan's execution ledger (the controller will give you the path). The voice of `architecture.md` and `project-state.md` is the job — they argue, name what was rejected, and record the branch's own mistakes. Do not write release notes.

- [ ] **Step 1: `docs/architecture.md`**

Add a section after the night-stream sections covering:

- **A ghost is its own `Voice`**, and why that one choice delivers both the birth ratio (the gain balance of a co-located pair) and ghosts that outlive their source (the same pair, different lifetimes) with no second mechanism. Name the alternative — a `Voice` carrying a blend parameter that changes over its life — and why it was rejected.
- **Why `sources.py` imports no audio**, and that `plan.py` importing it is what keeps an eight-hour night plannable in microseconds. Same rule as `arrangement.py`, same reason.
- **Why sources take turns** rather than sounding together, and that the handover is covered by the outliving-ghost mechanism rather than by a crossfade written for the purpose. This is the part a reader will not re-derive.
- **The two determinism rules in the walk**: two indices per step, every draw before any branch. Say what breaks if either is violated — a night reproducible until the sources folder changes, and then silently not.
- **Why preparation is a separate command**, in one sentence about fans.

- [ ] **Step 2: `docs/project-state.md`**

Add a "Plan 5, Phase 3" section covering:

- What shipped, and that Phase 2 was **skipped rather than reordered** — with the ceiling-only reasoning, and the empty-band finding preserved for whoever revisits the microphone.
- **The placeholders by name**: `LOOPS_PER_SOURCE`, `LOOP_BARS`, `STRETCH_SPEED`, `MAX_SOURCE_RATIO`, `STAGE_MIN_S`/`STAGE_MAX_S`, `HANDOVER_COVER_S`, `OUTLIVE_CHANCE`, `MIN_PEAK_FRACTION`, the fold band. All invented; none listened to.
- **The deliberate difference from the spec**: one pooled pitch set per source rather than one per loop, and why.
- **Wind is still a dead steering row** — one of six, and it was passed over for this deliberately.
- **Ambient light was considered and needs a spike, not a design** — the best available proxy for *you have actually gone to bed*, and possibly unreadable on Apple Silicon.
- Whatever the implementers found in this plan's own reference code. Phase 1's plan contained six real defects; record this one's honestly, whatever the number turns out to be.
- The listening judgement, outstanding as always.

- [ ] **Step 3: `README.md`**

Add: drop audio into the sources folder, run `sleepmix prepare` when convenient, then `sleepmix night`. Say plainly that prepare is the slow part with the fans on, that it never happens at bedtime, and that a night with nothing prepared is pure synthesis rather than an error.

- [ ] **Step 4: Verify every claim**

Run the suite, then re-read each claim against the module it describes. Check every constant named still exists under that name, and that the environment variables and folder names match what `cli.py` and `sources.py` actually use. Phase 1's documentation review found an invented quotation, a cross-reference pointing nowhere, and a claim that was the opposite of the truth — all three in prose that read as careful.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md docs/project-state.md README.md
git commit -m "docs: the ghost, and the values nobody has slept on"
```

---

## Self-review

**Spec coverage.** Every section maps to a task: the pitch set (Task 1), `SourceProfile` and its audio-free rule (Task 2), `prepare` and the fans (Task 3), sources taking turns with the pitch-distance preference (Task 4), the pair, the birth ratio and both flavours of outliving ghost (Task 5), playing a prepared loop (Task 6), wiring and the re-proved invariant (Task 7), the placeholders and the skipped Phase 2 (Task 8).

**One deliberate difference from the spec**, recorded rather than silent: the spec says the pitch set holds "the frequencies actually present in **each loop**"; this ships one pooled set per source. `SourceProfile` carries one set, a ghost of *this song* is the more useful object than a ghost of *this loop*, and the handover preference reasons at song level. Task 3 names it and Task 8 documents it.

**Type consistency, checked after writing.** `SourceProfile`'s five fields are used with the same names in `sources.py`, `prepare.py`, `plan.py`, `palette.py` and every test. `render_voice` gains its `profiles` parameter last with a default, so `stream._rendered` is the only production call site that changes. `Voice`'s three new fields are last and keyword-defaulted, so every Phase 1 construction still compiles — and the tests use keywords throughout, per hazard 4.

**Two things I could not check by writing and have flagged in place:**

- **Task 7's CLI test collides with a Phase 1 decision.** The `sounddevice` check was deliberately moved above every `click.echo` so a user without the extra does not read three lines of encouragement before an error. That means the new mode line prints after the check and a test forcing the import to fail cannot see it. The task says to resolve it with a fake `sounddevice` module rather than by moving the check back — undoing a fix to make a test easier is how the fix stops being a fix.
- **`stage_at` is a linear scan over the schedule.** A night holds at most a few dozen stages and the planner calls it once per walk step, so this is a few thousand comparisons per night — measured against Phase 1's sub-millisecond plan, it will not show. If Task 5's `test_planning_a_whole_night_with_sources_is_still_fast` fails, this is the first thing to look at, and a `bisect` over start frames is the fix.
