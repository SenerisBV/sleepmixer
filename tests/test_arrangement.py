"""The planner is pure, so all of this runs without audio, librosa or Demucs."""
import numpy as np
import pytest

from sleepmix.arrangement import (
    Arrangement, Placement, SegmentInfo, plan_arrangement, xfade_frames)
from sleepmix.config import ArrangementConfig, MixConfig, NothingToRender
from sleepmix.disintegration import plan_iterations
from sleepmix.util import lerp, shape_progress

SR = 22050


def _seg(n_frames=SR * 4):
    return SegmentInfo(source_id="song-1", index=0, n_frames=n_frames)


def _cfg(**arrangement):
    c = MixConfig()
    c.arrangement = ArrangementConfig(**arrangement)
    return c


# Used to build boundary targets for test_defaults_reproduce_todays_positions
# below: the default segment length and the stride between repeats it
# produces at default (zero) gaps and the default crossfade.
_DEFAULT_XFADE = xfade_frames(MixConfig().output.cycle_crossfade_ms, SR * 4, SR)
_DEFAULT_STRIDE = SR * 4 - _DEFAULT_XFADE


@pytest.mark.parametrize("target", [
    SR * 60,
    SR * 4,                          # == L, the segment length (k == 0)
    SR * 4 - 1,                      # L - 1
    SR * 4 + 1,                      # L + 1
    SR * 4 + _DEFAULT_STRIDE,        # L + 1 * stride, exact boundary
    SR * 4 + 18 * _DEFAULT_STRIDE,   # L + 18 * stride, exact boundary
], ids=["sr60", "L", "L-1", "L+1", "L+stride", "L+18stride"])
def test_defaults_reproduce_todays_positions(target):
    """The regression that makes this whole change safe.

    ``plan_iterations`` is retained as the oracle: at default gaps the planner
    must place repeats at exactly the frames the current renderer does, and
    produce exactly as many.

    Parametrised over several targets rather than one arbitrary duration:
    mutating the stopping rule's ``>=`` to ``>`` only diverges from
    ``plan_iterations`` when ``target`` lands exactly on ``L + k * stride``
    for some integer ``k`` — including ``k == 0``, i.e. ``target == L``
    itself. An arbitrary round-seconds duration like ``SR * 60`` essentially
    never lands there by chance, which is why a single-target version of this
    test cannot see the off-by-one the docstring above ``plan_arrangement``
    warns about."""
    seg = _seg()
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


def test_decay_progress_is_index_normalised_not_span_normalised():
    """``i / (n - 1)`` and span-normalising by position
    (``(p - p0) / (p_last - p0)``) agree exactly whenever gaps are uniform —
    which is every case ``test_the_decay_arc_reaches_both_ends`` checks,
    since it uses default (zero) gaps, where position is already a linear
    function of index. They diverge once the gap widens partway through,
    because then position stops being linear in index while ``i / (n - 1)``
    does not change shape. This is the case that tells the two formulas
    apart."""
    plan = plan_arrangement([_seg()], _cfg(gap_end_s=8.0), SR * 120, SR)
    n = len(plan.placements)
    assert n > 2, "need at least 3 placements for the two formulas to diverge"
    for i, p in enumerate(plan.placements):
        assert p.decay_progress == pytest.approx(i / (n - 1))


def test_gap_curve_actually_shapes_the_gap():
    """``gap_curve`` is a three-way, user-facing control (``config.py``), and
    ``shape_progress`` is the only thing standing between it and being a
    field that does nothing. Both curves agree on the very first stride —
    elapsed is 0 at the first placement regardless of curve — but must
    diverge from the second gap onward: bypassing ``shape_progress`` in
    favour of the bare elapsed fraction reproduces "linear" behaviour no
    matter what ``gap_curve`` says."""
    target = SR * 120
    linear = plan_arrangement(
        [_seg()], _cfg(gap_end_s=8.0, gap_curve="linear"), target, SR)
    exp = plan_arrangement(
        [_seg()], _cfg(gap_end_s=8.0, gap_curve="exp"), target, SR)
    linear_starts = [p.start_frame for p in linear.placements]
    exp_starts = [p.start_frame for p in exp.placements]
    assert len(linear_starts) > 2 and len(exp_starts) > 2
    assert linear_starts[:2] == exp_starts[:2]
    assert linear_starts != exp_starts


def test_gap_widens_by_elapsed_time_not_by_repeat_index():
    """The docstring's central claim about pass one: the gap is shaped by
    *elapsed time* (``pos / target_frames``), not by how many repeats have
    played so far. This reimplements the position-elapsed formula directly,
    independently of ``arrangement.py``, and asserts the planner matches it
    frame for frame. Any index-derived elapsed fraction (e.g. the repeat
    count so far over an estimated total) still produces some increasing
    sequence of gaps, so it can pass every test here that only checks
    monotonicity, counts, or endpoints; it cannot survive a frame-exact
    comparison against the time-based formula the docstring specifies."""
    seg = _seg()
    target = SR * 90
    xfade = xfade_frames(MixConfig().output.cycle_crossfade_ms, seg.n_frames, SR)
    floor = max(int(seg.n_frames * 0.1), 1)

    expected = []
    pos = 0
    while target > 0:
        expected.append(pos)
        if pos + seg.n_frames >= target:
            break
        elapsed = min(pos / target, 1.0)
        gap_s = lerp(1.0, 10.0, shape_progress(elapsed, "exp"))
        stride = max(seg.n_frames - xfade + int(gap_s * SR), floor)
        pos += stride

    plan = plan_arrangement(
        [seg], _cfg(gap_start_s=1.0, gap_end_s=10.0, gap_curve="exp"),
        target, SR)
    assert [p.start_frame for p in plan.placements] == expected


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
