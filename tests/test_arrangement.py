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
