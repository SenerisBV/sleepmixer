# Plan 4a: placement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make placement a first-class thing — the gap between successive repeats of a loop becomes a shaped, configurable quantity instead of one constant, so a mix can breathe or stack instead of only repeating back to back.

**Architecture:** A new pure module, `sleepmix/arrangement.py`, decides *where every repeat lands and how decayed it is* before any audio is touched, and hands back a flat list of `Placement` records. The renderer and the preview both read that same list, which is why they cannot drift — the pattern `plan_stem_configs` and `plan_iterations` already establish here. Defaults place every repeat exactly where the current renderer places it, and a regression test asserts that against `plan_iterations` as the oracle.

**Tech Stack:** Python 3.11 · numpy / scipy · pytest. No frontend work at all: the three new config fields generate their own controls from `/api/schema`.

**Spec:** `docs/superpowers/specs/2026-08-08-arrangement-design.md`

**Branch:** `feat/arrangement` (already created; the spec is committed on it).

## Global Constraints

- **`pipenv` runs only from `/Users/moopius/projects/sleepmixer`. Never `cd` elsewhere first** — pipenv keys its virtualenv to the directory path, and `cd`-ing first silently creates a new empty virtualenv.
- **No new Python dependencies.** Everything here is numpy plus what `sleepmix.util` already provides.
- **No frontend changes.** Do not touch anything under `ui/`, and do not run `make ui`. The new controls are generated from the schema. If you find yourself editing Elm, you have misread the plan.
- **Every server you start uses `SLEEPMIX_DATA_DIR=$(mktemp -d)`** and is killed afterwards. A prior implementer wrote into the operator's real music library before noticing.
- **Do not run a real full render, and do not run real Demucs.** Use the `stub_separation` fixture in `tests/conftest.py`; a `duration_min` of 0.05 finishes in under a second.
- **No browser automation, AppleScript, screenshots, or browser-driver MCPs.** Verify with `curl`.
- **`MixConfig.validate` and schema `min`/`max` metadata must agree.** `ui/README.md` states the rule: bounds are the schema's job, because the mixer clamps to them, and *"a control that can produce a value the config refuses turns a slider into a 400 on a preview, which is a much worse way to find out."*
- **Any dataclass added to `_SECTION_TYPES` needs a real docstring.** `_describe_type` raises on a dataclass-synthesised one, deliberately — a section with no description would render as a heading with nothing under it.
- Baseline at plan start: **299 Python tests collected.**

---

## Notes for whoever executes this

**What this plan is not.** The spec describes the whole arc — multiple segments per song, multiple source files, per-segment lifetimes, `find_loops`. **None of that is here.** This plan ships one segment from one source, and the only thing that changes is where its repeats land. Plan 4b adds segments and lifetimes; 4c adds sources.

That is why `ArrangementConfig` in this plan has exactly **three fields** and not the seven in the spec. Every field on a dataclass in `_SECTION_TYPES` becomes a control in the mixer automatically, so shipping `segments`, `segment_overlap`, `lifetime_jitter` and `order` now would put four controls on screen that do nothing. This codebase already withholds a control on purpose (`separation_model`) and documents why at the point of exclusion; do the same thing here by simply not adding the fields yet.

**The two riskiest things, in order:**

1. **The stopping rule.** `build_disintegrating_stream` breaks when the *write head* — the end of the repeat just placed — reaches `target_frames`, not when the next *start* would. Get this wrong by one and the placement regression in Task 4 fails, which is the good outcome; get it wrong in a way that still passes and every mix silently changes length. The arithmetic is worked out in Task 2 and the test asserts equality against `plan_iterations`, which is retained precisely as that oracle.

2. **Decay progress indexes by repeat, not by time.** `i / max(n - 1, 1)`. Normalising a repeat's *position* over the mix instead caps the arc below 1.0, so a render never reaches full decay — the same defect `plan_iterations`' docstring records being fixed once already. Task 2 has a dedicated test for both endpoints because every other test in the file passes either way.

**One deliberate asymmetry, and it will look like a mistake if you don't read this.** The gap is shaped by *elapsed time* (`pos / target_frames`), while decay progress is indexed by *repeat number*. That is not an oversight:

- Gaps widening is something a listener hears **in seconds** — "it's spacing out as it goes."
- Decay is the tape metaphor: **each pass** through the machine erodes it a little more. A mix should not decay faster per repeat merely because the repeats have moved further apart.

Using time for the gap also dodges a chicken-and-egg problem, since the repeat count is not known until the positions are laid out.

---

## File structure

| File | Responsibility |
|---|---|
| `sleepmix/arrangement.py` *(create)* | The whole of this plan's thinking. Three frozen dataclasses and one pure function. Touches no audio, imports nothing that does. |
| `tests/test_arrangement.py` *(create)* | Planner tests. No audio, no librosa, no Demucs — runs in milliseconds. |
| `sleepmix/config.py` *(modify)* | `ArrangementConfig`, its field on `MixConfig`, its `_SECTION_TYPES` entry, its bounds in `validate`. |
| `sleepmix/disintegration.py` *(modify)* | `render_arrangement` — places decayed repeats per the plan, applying the seam rule. `build_disintegrating_stream` becomes a thin wrapper. |
| `sleepmix/pipeline.py` *(modify)* | `_process_stem` builds a plan and renders it. |
| `sleepmix/preview.py` *(modify)* | `preview_iteration_index` reads the plan; `master_gain` measures the densest window rather than assuming frame 0. |
| `sleepmix/session.py` *(modify)* | `_master_key` gains `config.arrangement`. |
| `tests/test_disintegration.py` *(modify)* | Seam-rule tests. |
| `tests/test_pipeline.py` *(modify)* | The placement regression against `plan_iterations`. |
| `tests/test_preview.py` *(modify)* | Densest-window tests. |
| `tests/test_config.py` *(modify)* | Schema and round-trip tests. |

---

## Task 1: `ArrangementConfig`

**Files:**
- Modify: `sleepmix/config.py` (add the dataclass near `LoopConfig`; add the field to `MixConfig`; extend `validate`; register in `_SECTION_TYPES`)
- Test: `tests/test_config.py` *(modify)*

**Interfaces:**
- Consumes: nothing from any other task. `config.py` must not import `arrangement.py` — `arrangement.py` imports *it*, and this task runs first so the planner has a config to read.
- Produces: `ArrangementConfig(gap_start_s: float, gap_end_s: float, gap_curve: str)` and `MixConfig.arrangement: ArrangementConfig`.

**Three fields, not seven.** The spec's `segments`, `segment_overlap`, `lifetime_jitter` and `order` belong to Plan 4b. Every field here becomes a mixer control automatically; adding one that does nothing is the failure this task exists to avoid.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_the_arrangement_section_is_published_to_the_ui():
    schema = config_schema()
    assert "arrangement" in schema["sections"]
    fields = schema["sections"]["arrangement"]["fields"]
    assert set(fields) == {"gap_start_s", "gap_end_s", "gap_curve"}
    assert schema["sections"]["arrangement"]["description"]


def test_every_arrangement_field_carries_the_bounds_the_config_enforces():
    """A control that can produce a value ``validate`` refuses turns a slider
    into a 400 on a preview."""
    fields = config_schema()["sections"]["arrangement"]["fields"]
    for name in ("gap_start_s", "gap_end_s"):
        assert fields[name]["min"] == -30.0
        assert fields[name]["max"] == 120.0
    assert fields["gap_curve"]["choices"] == ["linear", "exp", "log"]


def test_arrangement_round_trips_through_from_dict():
    cfg = MixConfig.from_dict(
        {"arrangement": {"gap_start_s": 1.5, "gap_end_s": 9.0,
                         "gap_curve": "exp"}})
    assert cfg.arrangement.gap_start_s == 1.5
    assert cfg.arrangement.gap_end_s == 9.0
    assert cfg.arrangement.gap_curve == "exp"


def test_arrangement_defaults_are_todays_behaviour():
    cfg = MixConfig()
    assert cfg.arrangement.gap_start_s == 0.0
    assert cfg.arrangement.gap_end_s == 0.0
    assert cfg.arrangement.gap_curve == "linear"


def test_a_gap_outside_the_published_bounds_is_refused():
    with pytest.raises(ValueError, match="gap_start_s"):
        MixConfig.from_dict({"arrangement": {"gap_start_s": -100.0}})
    with pytest.raises(ValueError, match="gap_end_s"):
        MixConfig.from_dict({"arrangement": {"gap_end_s": 500.0}})


def test_an_unknown_gap_curve_is_refused():
    with pytest.raises(ValueError, match="gap_curve"):
        MixConfig.from_dict({"arrangement": {"gap_curve": "sigmoid"}})
```

Check the top of `tests/test_config.py` for its existing imports; add `config_schema` and `pytest` if they are not already there.

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_config.py -v -k arrangement`
Expected: FAIL — `KeyError: 'arrangement'` and `AttributeError: 'MixConfig' object has no attribute 'arrangement'`.

- [ ] **Step 3: Add the dataclass**

In `sleepmix/config.py`, after `LoopConfig`:

```python
@dataclass
class ArrangementConfig:
    """How much space sits between one repeat of the loop and the next.

    A mix used to be the loop repeated back to back, forever, at one fixed
    stride. These two numbers let that stride grow as the mix goes on — so the
    loop breathes, arriving less often as it erodes — or go negative, so
    repeats overlap and play over each other."""

    gap_start_s: float = field(default=0.0, metadata={
        "label": "Gap at the start", "min": -30.0, "max": 120.0, "step": 0.5,
        "unit": "s",
        "help": "Silence between one repeat and the next, early in the mix. "
                "Negative overlaps them instead."})
    gap_end_s: float = field(default=0.0, metadata={
        "label": "Gap at the end", "min": -30.0, "max": 120.0, "step": 0.5,
        "unit": "s",
        "help": "The same, late in the mix. Larger than the start gap and the "
                "loop spaces out as it dissolves."})
    gap_curve: str = field(default="linear", metadata={
        "label": "Gap curve", "choices": ["linear", "exp", "log"],
        "help": "How the gap travels from start to end — the same curves the "
                "decay uses. exp holds the early spacing longer; log opens "
                "up quickly then settles."})
```

- [ ] **Step 4: Add the field, the validation and the registration**

On `MixConfig`, beside the other section fields:

```python
    arrangement: ArrangementConfig = field(default_factory=ArrangementConfig)
```

In `MixConfig.validate`, after the seed check:

```python
        arr = self.arrangement
        for name in ("gap_start_s", "gap_end_s"):
            value = float(getattr(arr, name))
            # These bounds are the ones config_schema publishes; the mixer
            # clamps to them, so a value outside here can only arrive from a
            # hand-written config or an old preset. Refusing at construction
            # keeps it from surfacing as a 400 on a preview instead.
            if not -30.0 <= value <= 120.0:
                raise ValueError(
                    f"arrangement.{name} must be between -30 and 120 seconds, "
                    f"got {value}")
        if arr.gap_curve not in ("linear", "exp", "log"):
            raise ValueError(
                f"arrangement.gap_curve must be one of linear, exp, log; "
                f"got {arr.gap_curve!r}")
```

In `_SECTION_TYPES`:

```python
    "arrangement": ArrangementConfig,
```

- [ ] **Step 5: Run the config tests**

Run: `pipenv run pytest tests/test_config.py -v`
Expected: PASS. `tests/test_arrangement.py` does not exist yet — it arrives in Task 2, which reads the config this task just added.

- [ ] **Step 6: Confirm the mixer picks it up with no frontend change**

```bash
export SLEEPMIX_DATA_DIR=$(mktemp -d)
pipenv run python -c "
from sleepmix.config import config_schema
import json
print(json.dumps(config_schema()['sections']['arrangement'], indent=2))
"
```

Expected: the section, its description and three fields with their bounds. **Do not run `make ui`.** The controls are generated from this.

- [ ] **Step 7: Commit**

```bash
git add sleepmix/config.py tests/test_config.py
git commit -m "feat: the gap between repeats becomes a setting"
```

---

## Task 2: The pure planner

**Files:**
- Create: `sleepmix/arrangement.py`
- Test: `tests/test_arrangement.py`

**Interfaces:**
- Consumes: `sleepmix.util.lerp`, `sleepmix.util.shape_progress`, `sleepmix.config.NothingToRender`. `sleepmix.disintegration.plan_iterations` in tests only, as the regression oracle.
- Produces: `SegmentInfo(source_id: str, index: int, n_frames: int)`; `Placement(source_id, index, start_frame: int, decay_progress: float, n_frames: int)`; `Arrangement(placements: list[Placement], n_frames: int)` with `.at(frame: int) -> list[Placement]`; `xfade_frames(crossfade_ms: float, seg_frames: int, sr: int) -> int`; `plan_arrangement(segments: list[SegmentInfo], config: MixConfig, target_frames: int, sr: int) -> Arrangement`.

**Note on `Placement.n_frames`:** the spec lists four fields; this adds the segment's length as a fifth. It is denormalised, and it is what lets `Arrangement.at()` answer "what sounds here" without a side table of segment lengths — which is the spec's own stated goal for the record being self-describing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arrangement.py`:

```python
"""The planner is pure, so all of this runs without audio, librosa or Demucs."""
import numpy as np
import pytest

from sleepmix.arrangement import (
    Arrangement, Placement, SegmentInfo, plan_arrangement, xfade_frames)
from sleepmix.config import ArrangementConfig, MixConfig, NothingToRender
from sleepmix.disintegration import plan_iterations

SR = 22050


def _seg(n_frames=SR * 4):
    return SegmentInfo(source_id="song-1", index=0, n_frames=n_frames)


def _cfg(**arrangement):
    c = MixConfig()
    c.arrangement = ArrangementConfig(**arrangement)
    return c


def test_defaults_reproduce_todays_positions():
    """The regression that makes this whole change safe.

    ``plan_iterations`` is retained as the oracle: at default gaps the planner
    must place repeats at exactly the frames the current renderer does, and
    produce exactly as many."""
    seg = _seg()
    target = SR * 60
    plan = plan_arrangement([seg], _cfg(), target, SR)

    n_iter, xfade = plan_iterations(
        seg.n_frames, target, MixConfig().output.cycle_crossfade_ms, SR)
    stride = seg.n_frames - xfade

    assert len(plan.placements) == n_iter
    assert [p.start_frame for p in plan.placements] == [
        i * stride for i in range(n_iter)]


def test_the_decay_arc_reaches_both_ends():
    """First repeat exactly fresh, last exactly ruined.

    Normalising a repeat's *position* over the mix instead of its *index*
    passes every other test in this file while capping the arc below 1.0, so
    a render never reaches full decay. That is the defect
    ``plan_iterations``' docstring records being fixed once already."""
    plan = plan_arrangement([_seg()], _cfg(), SR * 60, SR)
    assert plan.placements[0].decay_progress == 0.0
    assert plan.placements[-1].decay_progress == 1.0


def test_progress_rises_monotonically():
    plan = plan_arrangement([_seg()], _cfg(), SR * 60, SR)
    progress = [p.decay_progress for p in plan.placements]
    assert progress == sorted(progress)


def test_gaps_widen_when_the_end_gap_is_larger():
    plan = plan_arrangement(
        [_seg()], _cfg(gap_start_s=0.0, gap_end_s=8.0), SR * 120, SR)
    starts = [p.start_frame for p in plan.placements]
    strides = np.diff(starts)
    assert len(strides) >= 3
    assert strides[-1] > strides[0]
    # monotonic, not merely bigger at the end
    assert list(strides) == sorted(strides)


def test_a_positive_gap_produces_fewer_repeats_than_none():
    target = SR * 120
    tight = plan_arrangement([_seg()], _cfg(), target, SR)
    loose = plan_arrangement([_seg()], _cfg(gap_start_s=5.0, gap_end_s=5.0),
                             target, SR)
    assert len(loose.placements) < len(tight.placements)


def test_a_negative_gap_makes_repeats_overlap():
    seg = _seg()
    plan = plan_arrangement(
        [seg], _cfg(gap_start_s=-2.0, gap_end_s=-2.0), SR * 120, SR)
    starts = [p.start_frame for p in plan.placements]
    # consecutive repeats start closer together than one segment length
    assert all(b - a < seg.n_frames for a, b in zip(starts, starts[1:]))


def test_stride_is_floored_so_a_huge_negative_gap_cannot_explode():
    """A stride below a tenth of a segment is a comb filter, not an overlap —
    and would let one config produce millions of placements."""
    seg = _seg()
    plan = plan_arrangement(
        [seg], _cfg(gap_start_s=-999.0, gap_end_s=-999.0), SR * 120, SR)
    starts = [p.start_frame for p in plan.placements]
    strides = np.diff(starts)
    assert strides.min() >= int(seg.n_frames * 0.1)


def test_nothing_starts_past_the_target():
    target = SR * 60
    plan = plan_arrangement([_seg()], _cfg(), target, SR)
    assert all(p.start_frame < target for p in plan.placements)
    assert plan.n_frames == target


def test_the_same_config_plans_identically():
    a = plan_arrangement([_seg()], _cfg(gap_end_s=6.0), SR * 60, SR)
    b = plan_arrangement([_seg()], _cfg(gap_end_s=6.0), SR * 60, SR)
    assert a.placements == b.placements


def test_at_returns_what_sounds_at_a_frame():
    seg = _seg()
    plan = plan_arrangement([seg], _cfg(), SR * 60, SR)
    second = plan.placements[1]
    here = plan.at(second.start_frame + 10)
    assert second in here
    assert all(p.start_frame <= second.start_frame + 10 < p.start_frame + p.n_frames
               for p in here)


def test_an_empty_plan_raises_rather_than_returning_nothing():
    with pytest.raises(NothingToRender):
        plan_arrangement([_seg()], _cfg(), 0, SR)


def test_more_than_one_segment_is_not_yet_supported():
    segs = [_seg(), SegmentInfo(source_id="song-1", index=1, n_frames=SR * 4)]
    with pytest.raises(NotImplementedError):
        plan_arrangement(segs, _cfg(), SR * 60, SR)


def test_xfade_is_clamped_to_half_a_segment():
    assert xfade_frames(crossfade_ms=100_000, seg_frames=1000, sr=SR) == 500
    assert xfade_frames(crossfade_ms=1000, seg_frames=SR * 10, sr=SR) == SR
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pipenv run pytest tests/test_arrangement.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'sleepmix.arrangement'`. `ArrangementConfig` already exists (Task 1), so this is the only thing missing.

- [ ] **Step 3: Write the module**

Create `sleepmix/arrangement.py`:

```python
"""Where every repeat lands, decided before any audio is touched.

Until this module existed, exactly one line decided when a repetition
happened — ``plan_iterations``' ``stride = max(loop_frames - xfade, 1)`` — and
it was a constant. Everything upstream produces *a loop*; everything
downstream (reverb, gain, sum, bed, master) never learns how many repeats
there were or where they sat. This is that seam, made explicit.

**Why a plan rather than a smarter renderer.** ``preview.py`` opens by stating
the property the interactive half of this program depends on: ``apply_decay``
is a pure function of progress, so auditioning one point in the arc costs a
single iteration rather than twenty minutes. An arrangement therefore has to
stay *queryable at an arbitrary point in time without rendering what precedes
it*. A renderer that computed placement as it went could not answer that
without running up to the point asked about. A flat list can, in microseconds.

That is also why the renderer and the preview both read the list this returns
rather than each deriving positions: it is the same reason
``pipeline._plan_jobs`` defers to ``config.plan_stem_configs`` — two code paths
for one decision are two places for it to drift.

Nothing here imports audio. Segment *lengths* come in as data
(``SegmentInfo.n_frames``), which is what lets the whole module be tested
against invented numbers.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import MixConfig, NothingToRender
from .util import lerp, shape_progress

# A stride below this fraction of a segment stops being an overlap and starts
# being a comb filter — and, less musically, would let one config produce
# millions of placements out of a twenty-minute target.
MIN_STRIDE_FRACTION = 0.1


@dataclass(frozen=True)
class SegmentInfo:
    """A segment as the planner needs to know it: identity and length.

    ``n_frames`` is the length *after* time-stretching, because that is the
    length the renderer will actually place."""

    source_id: str
    index: int
    n_frames: int


@dataclass(frozen=True)
class Placement:
    """One repeat, at one frame, at one point in its decay.

    ``decay_progress`` is carried rather than derived by the renderer so that
    the plan is self-describing: a test can assert that the fourteenth repeat
    sits at 0.6 against plain values, with no audio in the room. ``n_frames``
    is denormalised from the segment for the same reason — it is what lets
    ``Arrangement.at`` answer "what sounds here" without a side table."""

    source_id: str
    index: int
    start_frame: int
    decay_progress: float
    n_frames: int


@dataclass(frozen=True)
class Arrangement:
    placements: list[Placement]
    n_frames: int

    def at(self, frame: int) -> list[Placement]:
        """Every placement sounding at ``frame``."""
        return [p for p in self.placements
                if p.start_frame <= frame < p.start_frame + p.n_frames]


def xfade_frames(crossfade_ms: float, seg_frames: int, sr: int) -> int:
    """The crossfade between consecutive repeats, clamped to half a segment.

    Extracted from ``plan_iterations`` so the planner and the existing
    renderer cannot disagree about it."""
    return min(int(crossfade_ms / 1000.0 * sr), seg_frames // 2)


def plan_arrangement(
    segments: list[SegmentInfo],
    config: MixConfig,
    target_frames: int,
    sr: int,
) -> Arrangement:
    """Lay out every repeat of every segment, in two passes.

    **Pass one places them.** The stopping rule is the one
    ``build_disintegrating_stream`` already applies: stop once the *write
    head* — the end of the repeat just placed — reaches ``target_frames``, not
    once the next start would. Off by one here and every mix silently changes
    length, which is why ``test_defaults_reproduce_todays_positions`` asserts
    equality against ``plan_iterations`` rather than against a hand-written
    list.

    **Pass two assigns decay progress**, and it indexes by *repeat*:
    ``i / max(n - 1, 1)``. The count is not known until the positions are laid
    out, which is what makes this two passes rather than one.

    Normalising a repeat's *position* over the mix instead is the obvious
    alternative and it is wrong: the last repeat begins a segment-length short
    of the end, so progress would top out below 1.0 and the arc would never
    reach full decay in output. That is precisely the defect
    ``plan_iterations``' docstring records being fixed once already, pointing
    the other way. Indexing by repeat is also the truer reading of the
    metaphor — each *pass* through the tape machine erodes it, and a mix
    should not decay faster per repeat merely because the repeats have moved
    further apart.

    **The gap, by contrast, is shaped by elapsed time** rather than by repeat
    index. Gaps widening is something heard in seconds ("it is spacing out as
    it goes"), and using time also sidesteps the same chicken-and-egg the
    progress pass has to solve with a second walk.
    """
    if len(segments) != 1:
        raise NotImplementedError(
            "Plan 4a places one segment from one source. Multi-segment "
            "lifetimes arrive in Plan 4b; see the arrangement design spec.")
    seg = segments[0]
    arr = config.arrangement
    xfade = xfade_frames(config.output.cycle_crossfade_ms, seg.n_frames, sr)
    floor = max(int(seg.n_frames * MIN_STRIDE_FRACTION), 1)

    positions: list[int] = []
    pos = 0
    while target_frames > 0:
        positions.append(pos)
        if pos + seg.n_frames >= target_frames:
            break
        elapsed = min(pos / target_frames, 1.0)
        gap_s = lerp(arr.gap_start_s, arr.gap_end_s,
                     shape_progress(elapsed, arr.gap_curve))
        stride = max(seg.n_frames - xfade + int(gap_s * sr), floor)
        pos += stride

    if not positions:
        raise NothingToRender(
            "This arrangement places no audio at all, so the render would be "
            "silence. Check the mix duration.")

    last = max(len(positions) - 1, 1)
    placements = [
        Placement(source_id=seg.source_id, index=seg.index, start_frame=p,
                  decay_progress=i / last, n_frames=seg.n_frames)
        for i, p in enumerate(positions)
    ]
    return Arrangement(placements=placements, n_frames=target_frames)
```

- [ ] **Step 4: Run the tests**

Run: `pipenv run pytest tests/test_arrangement.py -v`

Expected: PASS, every test in the file.

If `_cfg()` raises on `ArrangementConfig`, Task 1 has not landed — check `git log` before changing anything here. Do not work around it by inlining a stub config; the helper is meant to construct the real one.

- [ ] **Step 5: Commit**

```bash
git add sleepmix/arrangement.py tests/test_arrangement.py
git commit -m "feat: a plan for where every repeat lands"
```

---

## Task 3: The renderer reads a plan

**Files:**
- Modify: `sleepmix/disintegration.py`
- Test: `tests/test_disintegration.py` *(modify)*

**Interfaces:**
- Consumes: `arrangement.Arrangement`, `arrangement.Placement`, `arrangement.xfade_frames` from Task 2.
- Produces: `render_arrangement(loop: AudioBuffer, plan: Arrangement, decay: StemDecayConfig, crossfade_ms: float, seed: int, stem: str = "mix", cancel=None) -> AudioBuffer`. `build_disintegrating_stream` keeps its current signature and becomes a wrapper, so nothing outside this file breaks.

**The seam rule** is the whole of this task:

| overlap between consecutive repeats | treatment |
|---|---|
| ≤ `xfade` | equal-power crossfade — a join, exactly today |
| > `xfade` | additive sum — deliberate stacking, two voices |
| none (a gap) | nothing; silence between |

Crossfading a deliberate four-second stack would duck both voices through the overlap, which is the opposite of what "play over each other" means.

> **Correction, made during execution — read this before reusing Task 3's code in Plan 4b.** As originally written, this task's `render_arrangement` *assigned* into the overlap region in the crossfade branch, and justified it with a proof that no third repeat could reach that region: the branch runs when the overlap is at most `xfade`, `xfade` is clamped to half a segment, therefore the stride is at least half a segment, therefore the repeat two back has already ended. **The proof is false.** The branch condition constrains only the stride *into this placement*; the stride into the one before it is bounded by nothing there except `MIN_STRIDE_FRACTION`, a tenth of a segment. The two can sum to 0.6 of a segment with a third repeat still sounding — a heavy stack immediately followed by a seam, which a gap arc crossing from negative to positive produces from ordinary settings at the default `cycle_crossfade_ms` of 800 ms. It ducked up to ~0.92 s of that third voice to silence and snapped it back. Every test in the task used two placements, or three with no overlap, so none of them saw it.
>
> The docstring and the code below have been corrected to what shipped: the crossfade branch blends against the previous placement's *own chunk* and adds the difference, which is additive-safe by construction and needs no reachability argument at all. `test_a_seam_after_a_stack_keeps_the_stacked_voice` in `tests/test_disintegration.py` pins the case. Two further deviations from the code below also shipped and are not reflected here: `render_arrangement` calls `decayed_iteration` rather than `apply_decay` with an inline key (composing the rng key in exactly one place, so the preview and render paths cannot drift), and it raises `MalformedArrangement` for a placement that does not fit its buffer. See `docs/project-state.md`'s Plan 4a section for both incidents.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_disintegration.py`:

```python
from sleepmix.arrangement import Arrangement, Placement
from sleepmix.config import StemDecayConfig
from sleepmix.disintegration import render_arrangement

_FLAT = StemDecayConfig(enabled=False)   # decay off: assert on placement alone


def _plan(starts, seg_frames, target):
    return Arrangement(
        placements=[Placement("s", 0, st, 0.0, seg_frames)
                    for st in starts],
        n_frames=target)


def _dc(sr, secs, value=0.5):
    """A constant-valued buffer — sums and crossfades are readable on it."""
    n = int(sr * secs)
    return AudioBuffer(np.full((n, 1), value, dtype=np.float32), sr)


def test_a_gap_between_repeats_leaves_actual_silence():
    sr = 22050
    seg = _dc(sr, 1.0)
    # second repeat starts a full second after the first ends
    plan = _plan([0, sr * 2], seg.n_frames, sr * 3)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=0.0, seed=0)
    quiet = out.data[sr + 100: sr * 2 - 100]
    assert np.abs(quiet).max() < 1e-6


def test_an_overlap_within_the_crossfade_is_a_crossfade_not_a_sum():
    """Equal-power crossfade of two equal constants stays near the constant.
    Summing them would nearly double it."""
    sr = 22050
    seg = _dc(sr, 1.0, value=0.5)
    xfade_ms = 100.0
    stride = seg.n_frames - int(xfade_ms / 1000.0 * sr)
    plan = _plan([0, stride], seg.n_frames, stride + seg.n_frames)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=xfade_ms, seed=0)
    seam = out.data[stride: stride + int(xfade_ms / 1000.0 * sr)]
    assert seam.max() < 0.75          # nothing like 1.0
    assert seam.min() > 0.4           # and no dip to silence


def test_an_overlap_larger_than_the_crossfade_sums():
    """Deliberate stacking: two voices, not one seam."""
    sr = 22050
    seg = _dc(sr, 1.0, value=0.5)
    plan = _plan([0, sr // 2], seg.n_frames, sr * 2)   # half a segment apart
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=10.0, seed=0)
    stacked = out.data[sr // 2 + 100: sr - 100]
    assert stacked.max() > 0.95       # ~0.5 + 0.5


def test_the_output_is_exactly_the_planned_length():
    sr = 22050
    seg = _dc(sr, 1.0)
    plan = _plan([0, sr, sr * 2], seg.n_frames, sr * 3)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=0.0, seed=0)
    assert out.n_frames == sr * 3


def test_build_disintegrating_stream_still_works():
    """The wrapper keeps every existing caller and test honest."""
    sr = 22050
    seg = _dc(sr, 1.0)
    out = build_disintegrating_stream(
        seg, target_frames=sr * 5, decay=_FLAT, crossfade_ms=100.0,
        seed=0, stem="mix")
    assert out.n_frames == sr * 5
```

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_disintegration.py -v -k "arrangement or gap or overlap or planned"`
Expected: FAIL — `ImportError: cannot import name 'render_arrangement'`.

- [ ] **Step 3: Write `render_arrangement`**

In `sleepmix/disintegration.py`, add the imports and the function; then rewrite `build_disintegrating_stream` as a wrapper:

```python
from .arrangement import Arrangement, Placement, xfade_frames


def render_arrangement(
    loop: AudioBuffer,
    plan: Arrangement,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
    """Render every placement in ``plan``, each decayed to its own progress.

    **The seam rule.** Consecutive repeats can now relate three ways, and only
    one of them is the join this renderer used to assume. An overlap no larger
    than the crossfade is a seam and gets an equal-power crossfade, exactly as
    before. An overlap *larger* than the crossfade is deliberate stacking —
    the operator asked for two voices — and is summed, because crossfading it
    would duck both through the overlap, which is the opposite of playing over
    each other. A gap gets nothing, and the silence is the point.

    The crossfade branch blends against the *previous placement's own chunk*
    and adds the difference in, never assigning over whatever the accumulator
    already holds: ``out[region] += crossfade(prev_tail, chunk[:overlap]) -
    prev_tail``, where ``prev_tail`` is placement i-1's own last ``overlap``
    samples. The delta only ever replaces i-1's contribution, so anything
    else already in that region — i-2, i-3, any number of earlier voices the
    additive branch stacked there — survives untouched, for any existing
    content ``d``: ``d + prev_tail + (crossfade(prev_tail, b) - prev_tail) =
    d + crossfade(prev_tail, b)``. That is additive-safe by construction,
    with no argument about how far back an overlap can reach. Heavier
    stacking than the crossfade window takes the additive branch, where
    nothing is overwritten or subtracted.

    Randomness is still keyed per repeat through ``util.iteration_rng`` so a
    single repeat reproduces in isolation; see ``decayed_iteration``."""
    sr = loop.sr
    ch = loop.n_channels
    seg_len = loop.n_frames
    xfade = xfade_frames(crossfade_ms, seg_len, sr)

    out = np.zeros((plan.n_frames + seg_len, ch), dtype=np.float32)
    prev_end = None
    prev_chunk = None
    for i, placement in enumerate(plan.placements):
        if cancel is not None:
            cancel.check()
        chunk = apply_decay(
            loop, placement.decay_progress, decay,
            iteration_rng(seed, f"{placement.source_id}:{placement.index}:{stem}", i),
        ).data
        start = placement.start_frame
        overlap = 0 if prev_end is None else max(prev_end - start, 0)
        if 0 < overlap <= xfade:
            prev_tail = prev_chunk[-overlap:]
            blended = equal_power_crossfade(prev_tail, chunk[:overlap])
            out[start:start + overlap] += blended - prev_tail
            out[start + overlap:start + seg_len] += chunk[overlap:]
        else:
            out[start:start + seg_len] += chunk
        prev_end = start + seg_len
        prev_chunk = chunk

    return AudioBuffer(out[:plan.n_frames], sr)


def build_disintegrating_stream(
    loop: AudioBuffer,
    target_frames: int,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
    """Repeat ``loop`` back to back until ``target_frames``, degrading each pass.

    Retained as the zero-gap case of ``render_arrangement``, which is what
    every caller predating the arrangement wants and what
    ``tests/test_disintegration.py`` already pins down."""
    n_iter, xfade = plan_iterations(loop.n_frames, target_frames, crossfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)
    last = max(n_iter - 1, 1)
    plan = Arrangement(
        placements=[
            Placement("mix", 0, i * stride, i / last, loop.n_frames)
            for i in range(n_iter)
        ],
        n_frames=target_frames,
    )
    return render_arrangement(loop, plan, decay, crossfade_ms, seed, stem, cancel)
```

Note the rng key changed from `stem` to `f"{source}:{index}:{stem}"`. That reshuffles the noise relative to the old build, which is intentional. Task 4's regression is a *placement* comparison against `plan_iterations` rather than a byte comparison of audio, precisely so this key change does not falsely fail it.

- [ ] **Step 4: Run the disintegration tests**

Run: `pipenv run pytest tests/test_disintegration.py -v`
Expected: PASS. If a pre-existing test asserting exact sample values fails, it is asserting the old rng key — read it, confirm that is the cause, and update the expected values rather than reverting the key.

- [ ] **Step 5: Commit**

```bash
git add sleepmix/disintegration.py tests/test_disintegration.py
git commit -m "feat: render a plan, and tell a seam from a stack"
```

---

## Task 4: Wire the pipeline, and pin the output

**Files:**
- Modify: `sleepmix/pipeline.py` (`_process_stem`)
- Test: `tests/test_pipeline.py` *(modify)*

**Interfaces:**
- Consumes: `arrangement.SegmentInfo`, `arrangement.plan_arrangement`, `disintegration.render_arrangement`.
- Produces: no new public names. `_process_stem` keeps its signature.

**This is the task that makes the whole change safe.** The regression is a *placement* comparison, computed live against `plan_iterations` — no captured fixture, no binary artifact on disk. `plan_iterations` is retained in `disintegration.py` precisely to be that oracle, and comparing against it beats comparing against a recorded file: a fixture records what the code did on the day it was captured, whereas the oracle records what the code was always *supposed* to do.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_pipeline.py`:

```python
def test_default_arrangement_places_repeats_exactly_where_it_always_did():
    """The regression that makes the arrangement safe to land.

    Not a byte comparison of audio — the rng key deliberately changed, so
    sample values move. What must not move is *placement*: the same number of
    repeats, at the same frames, at the same decay progress the old renderer
    produced. That is the property every existing mix depends on."""
    from sleepmix.arrangement import SegmentInfo, plan_arrangement
    from sleepmix.disintegration import plan_iterations

    sr = 22050
    seg_frames = sr * 3
    target = sr * 30
    cfg = MixConfig()

    plan = plan_arrangement(
        [SegmentInfo("song", 0, seg_frames)], cfg, target, sr)
    n_iter, xfade = plan_iterations(
        seg_frames, target, cfg.output.cycle_crossfade_ms, sr)
    stride = seg_frames - xfade

    assert len(plan.placements) == n_iter
    assert [p.start_frame for p in plan.placements] == [
        i * stride for i in range(n_iter)]
    assert [p.decay_progress for p in plan.placements] == [
        i / max(n_iter - 1, 1) for i in range(n_iter)]


def test_a_gap_makes_the_render_use_fewer_repeats(tmp_path, stub_separation):
    """End to end, through run_pipeline, at a duration that finishes fast."""
    song = _write_test_song(tmp_path)          # see the helper this file uses
    cfg = MixConfig()
    cfg.output.duration_min = 0.05
    tight = _count_repeats(song, cfg, tmp_path / "a.wav")

    cfg.arrangement.gap_start_s = 3.0
    cfg.arrangement.gap_end_s = 3.0
    loose = _count_repeats(song, cfg, tmp_path / "b.wav")
    assert loose < tight
```

Read the top of `tests/test_pipeline.py` and reuse whatever helper it already has for writing a test song; if `_count_repeats` has no equivalent, implement it as a call to `plan_arrangement` with the same `SegmentInfo` the pipeline would build, rather than by analysing audio.

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_pipeline.py -v -k arrangement`
Expected: FAIL — `_process_stem` does not build a plan yet, so the end-to-end case does not change with the gap.

- [ ] **Step 3: Rewrite `_process_stem`**

In `sleepmix/pipeline.py`, replace the body's stream construction:

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
    # One plan per stem, from the same loop length, so every stem's repeats
    # land on the same frames and stay phase-aligned — the reason the loop
    # point is found once on the summed reference in the first place.
    plan = plan_arrangement(
        [SegmentInfo(source_id="mix", index=0, n_frames=loop.n_frames)],
        config, target_frames, loop.sr)
    stream = render_arrangement(
        loop, plan, sc.decay, config.output.cycle_crossfade_ms,
        config.seed, sc.name, cancel=cancel)
    stream = apply_reverb(stream, config.reverb, wet_scale=sc.reverb_send)
    if abs(sc.gain_db) > 1e-6:
        stream = AudioBuffer(stream.data * db_to_amp(sc.gain_db), stream.sr)
    return stream.with_channels(config.output.channels)
```

Add to the imports at the top of the file:

```python
from .arrangement import SegmentInfo, plan_arrangement
from .disintegration import render_arrangement
```

**Note the phase-alignment subtlety:** every stem is sliced from the same `loop_point` and stretched identically, so `loop.n_frames` is the same for all of them and each stem's plan is identical. Do not hoist the plan out of the loop to "optimise" it — it is cheap, and computing it per stem keeps the function honest about what it depends on.

- [ ] **Step 4: Run the pipeline tests**

Run: `pipenv run pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `pipenv run pytest -q`
Expected: 299 + the new tests, all passing. Investigate any failure rather than adjusting the assertion; a test that broke here is telling you something about placement.

- [ ] **Step 6: Commit**

```bash
git add sleepmix/pipeline.py tests/test_pipeline.py
git commit -m "feat: the renderer places repeats from a plan"
```

---

## Task 5: The preview follows the plan

**Files:**
- Modify: `sleepmix/preview.py` (`preview_iteration_index`)
- Test: `tests/test_preview.py` *(modify)*

**Interfaces:**
- Consumes: `arrangement.plan_arrangement`, `arrangement.SegmentInfo`.
- Produces: `preview_iteration_index(session, progress) -> tuple[int, int]` — unchanged signature, now derived from the plan.

**Why this is not optional.** `preview_iteration_index` currently calls `plan_iterations`, which knows nothing about gaps. With a positive gap the render has *fewer* repeats than `plan_iterations` reports, so the preview would audition an iteration the render never produces — the exact defect that function's docstring records being fixed once already.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_preview.py`:

```python
def test_the_preview_indexes_the_repeats_the_render_actually_produces(
        tmp_path, stub_separation):
    """With a gap, the render has fewer repeats. The preview must agree, or
    scrubbing to the end auditions an iteration that does not exist."""
    from sleepmix.arrangement import SegmentInfo, plan_arrangement

    song = _write_test_song(tmp_path)      # reuse this file's existing helper
    cfg = MixConfig()
    cfg.output.duration_min = 0.05
    cfg.arrangement.gap_start_s = 2.0
    cfg.arrangement.gap_end_s = 2.0

    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    loop = session.prepared_loop(session.stem_names()[0])
    target = int(cfg.output.duration_min * 60 * loop.sr)
    plan = plan_arrangement(
        [SegmentInfo("mix", 0, loop.n_frames)], cfg, target, loop.sr)

    _, n_iter = preview_iteration_index(session, 0.0)
    assert n_iter == len(plan.placements)

    last, _ = preview_iteration_index(session, 1.0)
    assert last == len(plan.placements) - 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pipenv run pytest tests/test_preview.py -v -k indexes`
Expected: FAIL — `n_iter` comes from `plan_iterations` and is larger than the plan's placement count.

- [ ] **Step 3: Rewrite `preview_iteration_index`**

```python
def preview_iteration_index(session: RenderSession, progress: float) -> tuple[int, int]:
    """Map a point in the arc to ``(index, n_placements)``.

    Reads the same ``plan_arrangement`` the renderer does, so the mapping
    cannot drift between preview and render. It used to read
    ``plan_iterations``, which is correct only when every repeat sits one
    stride from the last — with a gap the render produces fewer repeats, and
    a preview scrubbed to the end would audition one that does not exist."""
    cfg = session.config
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    plan = plan_arrangement(
        [SegmentInfo(source_id="mix", index=0, n_frames=loop.n_frames)],
        cfg, target_frames, loop.sr)
    n = len(plan.placements)
    p = float(np.clip(progress, 0.0, 1.0))
    return int(round(p * (n - 1))), n
```

Add to the imports:

```python
from .arrangement import SegmentInfo, plan_arrangement
```

- [ ] **Step 4: Run the preview tests**

Run: `pipenv run pytest tests/test_preview.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sleepmix/preview.py tests/test_preview.py
git commit -m "fix: the preview indexes the repeats the render produces"
```

---

## Task 6: `master_gain` stops assuming it knows where the peak is

**Files:**
- Modify: `sleepmix/preview.py` (`master_gain`)
- Modify: `sleepmix/session.py` (`_master_key`)
- Test: `tests/test_preview.py` *(modify)*, `tests/test_session.py` *(modify)*

**Interfaces:**
- Consumes: `arrangement.plan_arrangement`.
- Produces: `densest_frame(plan: Arrangement, decay: StemDecayConfig) -> int` in `sleepmix/arrangement.py`.

**The invariant that breaks.** `master_gain`'s docstring justifies measuring one window: *"decay only removes energy, so the peak falls monotonically across the arc and iteration 0 is the loudest window this module can produce."* With a negative gap, repeats overlap — and two near-fresh repeats sounding together beat one fresh repeat alone. A gain calibrated at frame 0 leaves the render's true peak above target.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arrangement.py`:

```python
def test_the_densest_frame_is_the_start_when_nothing_overlaps():
    from sleepmix.arrangement import densest_frame
    from sleepmix.config import StemDecayConfig

    plan = plan_arrangement([_seg()], _cfg(), SR * 60, SR)
    assert densest_frame(plan, StemDecayConfig()) == 0


def test_the_densest_frame_moves_when_repeats_stack():
    """Two near-fresh repeats sounding together beat one fresh repeat alone."""
    from sleepmix.arrangement import densest_frame
    from sleepmix.config import StemDecayConfig

    plan = plan_arrangement(
        [_seg()], _cfg(gap_start_s=-3.0, gap_end_s=-3.0), SR * 60, SR)
    frame = densest_frame(plan, StemDecayConfig())
    assert frame > 0
    assert len(plan.at(frame)) >= 2
```

Append to `tests/test_session.py`:

```python
def test_changing_the_gap_clears_the_memoised_gain(tmp_path, stub_separation):
    """The arrangement decides which window gets measured, so it belongs in
    the key — the same test ``_master_key``'s docstring applies to the sound
    bed: not whether a render reads the field, but whether the calibration
    window's own output depends on it."""
    song = _write_test_song(tmp_path)
    cfg = MixConfig()
    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    session.master_gain[True] = 0.5

    changed = MixConfig()
    changed.arrangement.gap_start_s = -2.0
    session.update_config(changed)
    assert session.master_gain == {}
```

- [ ] **Step 2: Run to verify they fail**

Run: `pipenv run pytest tests/test_arrangement.py tests/test_session.py -v -k "densest or gap"`
Expected: FAIL — `ImportError: cannot import name 'densest_frame'`, and the session test finds the memo intact.

- [ ] **Step 3: Add `densest_frame`**

In `sleepmix/arrangement.py`:

```python
def densest_frame(plan: Arrangement, decay: StemDecayConfig) -> int:
    """The frame where the most amplitude is likely to coincide.

    ``preview.master_gain`` measures one window and used to assume it was the
    first: decay only removes energy, so the peak fell monotonically and
    iteration 0 was the loudest thing that module could produce. Overlapping
    repeats break that — two near-fresh repeats sounding together beat one
    fresh repeat alone, and a gain calibrated at frame 0 leaves the real peak
    above target.

    The proxy below only has to *rank* candidates; the level is still measured
    by rendering the winning window for real. Candidates are the placement
    starts themselves, because the sum of concurrent amplitudes only changes
    where a placement begins or ends."""
    from .util import db_to_amp

    def amplitude(p: Placement) -> float:
        if not decay.enabled:
            return 1.0
        shaped = shape_progress(p.decay_progress, decay.curve)
        return db_to_amp(lerp(decay.amp_start_db, decay.amp_end_db, shaped))

    best_frame, best = 0, -1.0
    for candidate in plan.placements:
        frame = candidate.start_frame
        total = sum(amplitude(p) for p in plan.at(frame))
        if total > best:
            best, best_frame = total, frame
    return best_frame
```

Add `StemDecayConfig` to the `from .config import ...` line.

- [ ] **Step 4: Point `master_gain` at it**

In `sleepmix/preview.py`, inside `master_gain`, replace the fixed `0.0` progress:

```python
    cached = session.master_gain.get(reverb)
    if cached is None:
        cfg = session.config
        name = session.stem_names()[0]
        loop = session.prepared_loop(name)
        target_frames = int(cfg.output.duration_min * 60 * loop.sr)
        plan = plan_arrangement(
            [SegmentInfo(source_id="mix", index=0, n_frames=loop.n_frames)],
            cfg, target_frames, loop.sr)
        here = plan.at(densest_frame(plan, cfg.stems[0].decay))
        # The window to measure is the one carrying the most concurrent
        # amplitude, not necessarily the first. With no overlap this is
        # progress 0 and the behaviour is exactly what it always was.
        progress = min(p.decay_progress for p in here) if here else 0.0
        loudest = render_window(session, progress, reverb=reverb, master=False)
        peak = float(np.abs(loudest.data).max())
        target = db_to_amp(session.config.output.peak_db)
        cached = float(target / peak) if peak > 1e-9 else 1.0
        session.master_gain[reverb] = cached
    return cached
```

Update the import line to bring in `densest_frame`.

Also update `master_gain`'s docstring: the sentence beginning *"One window per path is enough: decay only removes energy…"* is now false as written. Replace it with a statement that the window is chosen by `densest_frame`, and why.

- [ ] **Step 5: Add `arrangement` to the master key**

In `sleepmix/session.py`, in `_master_key`'s returned tuple:

```python
            tuple(sorted(asdict(config.arrangement).items())),
```

And add a paragraph to its docstring — this is the third instance of the distinction that docstring already draws twice, so it should say so:

```
        ``config.arrangement`` is here for the same reason ``config.soundbed``
        is, and it is the third instance of the distinction drawn above. The
        question is never whether a real render reads the field — it is
        whether the *calibration window's own output* depends on it. It does:
        ``master_gain`` now asks ``arrangement.densest_frame`` which window to
        measure, so a changed gap can move the measurement to a different
        point in the arc entirely.
```

- [ ] **Step 6: Run the tests**

Run: `pipenv run pytest tests/test_preview.py tests/test_session.py tests/test_arrangement.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `pipenv run pytest -q`
Expected: all green.

- [ ] **Step 8: Verify end to end against a running server**

```bash
export SLEEPMIX_DATA_DIR=$(mktemp -d)
pipenv run sleepmix ui --port 8765 &
sleep 3
curl -s localhost:8765/api/schema | python3 -c "
import json,sys
s = json.load(sys.stdin)['sections']['arrangement']
print(s['description'][:60])
print(sorted(s['fields']))
"
curl -s localhost:8765/api/config/default | python3 -c "
import json,sys; print(json.load(sys.stdin)['arrangement'])
"
kill %1
```

Expected: the section description, `['gap_curve', 'gap_end_s', 'gap_start_s']`, and defaults of `0.0 / 0.0 / linear`.

- [ ] **Step 9: Commit**

```bash
git add sleepmix/preview.py sleepmix/session.py sleepmix/arrangement.py \
        tests/test_preview.py tests/test_session.py tests/test_arrangement.py
git commit -m "fix: measure the loudest window, not the first one"
```

---

## Task 7: Documentation

**Files:**
- Modify: `docs/architecture.md`, `docs/project-state.md`, `README.md`

- [ ] **Step 1: `docs/architecture.md`**

Add a section on the arrangement seam: that placement is now a plan rather than a constant, that the plan is pure and queryable at a frame, and that the renderer and preview both read it so they cannot drift. State the two-pass layout and why decay indexes by repeat while the gap is shaped by time.

- [ ] **Step 2: `docs/project-state.md`**

Record: Plan 4a complete; `ArrangementConfig` has three fields and **4b will add four more** (`segments`, `segment_overlap`, `lifetime_jitter`, `order`) — this is the placeholder-for-future-functionality note the operator's standing instructions require. Also record that `plan_iterations` is retained **as the regression oracle** for `test_defaults_reproduce_todays_positions` and has no production caller left, so nobody deletes it as dead code.

- [ ] **Step 3: `README.md`**

Add the three settings to the config documentation, with the one-line description of what a positive and a negative gap do.

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md
git commit -m "docs: placement becomes a plan, and what that opens"
```

---

## Self-review notes

Checked against the spec's Plan 4a scope:

- **`ArrangementConfig`, planner, renderer reading a plan, the seam rule, `master_gain` argmax, placement regression** — Tasks 1, 2, 3, 3, 6, 4 respectively. Covered.

- **Task order note (amended before execution):** the config lands first and the planner second, so every task commits with its own tests green. The original ordering had the planner's test file importing `ArrangementConfig` a task before it existed. The two have no dependency in the other direction — `config.py` must never import `arrangement.py`.
- **Lifetimes, `segments`, `segment_overlap`, `lifetime_jitter`, `order`, `find_loops`, `ArrangementSession`, `render_arrangement_window`** — all deferred to 4b/4c, stated in "Notes for whoever executes this" and again in Task 7 Step 2 so the deferral is recorded in project state rather than lost.
- **One deviation from the spec:** `Placement` gains `n_frames` (five fields, not four), so `Arrangement.at()` needs no side table. Recorded in Task 2's Interfaces block.
- **One correction the spec does not carry:** the bit-identity regression is a **placement** comparison, not a byte comparison of audio. Task 3 changes the `iteration_rng` key to `f"{source}:{index}:{stem}"` — required so that adding sources in 4c does not reshuffle existing noise — and that moves sample values. What must not move is the number of repeats, their frames, and their decay progress. Task 4's test asserts exactly that. Anyone reading the spec's "bit-identical" wording alone would write a test that fails for a legitimate reason.
