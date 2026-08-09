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
    comparison against the time-based formula the docstring specifies.

    The loop below mirrors ``plan_arrangement``'s own stopping condition —
    ``while pos < target`` rather than ``while target > 0`` with the
    in-range check omitted — for the same reason that one was fixed: at this
    target (90s) an exp curve from a 1s to a 10s gap makes the stride large
    enough, late enough, to leap past the end of the target before that gets
    checked, and an unguarded reimplementation here would assert against a
    position ``plan_arrangement`` no longer produces rather than genuinely
    mirroring it."""
    seg = _seg()
    target = SR * 90
    xfade = xfade_frames(MixConfig().output.cycle_crossfade_ms, seg.n_frames, SR)
    floor = max(int(seg.n_frames * 0.1), 1)

    expected = []
    pos = 0
    while pos < target:
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


@pytest.mark.parametrize(
    "seg_seconds, gap_start_s, gap_end_s, gap_curve, target_s, crossfade_ms",
    [
        (4, 0.0, 0.0, "linear", 60, 800.0),     # defaults — the original case
        # The reported reproducer: a strongly positive-going gap arc lets one
        # stride leap past what remains of the target, and the position that
        # leap lands on used to get appended anyway. render_arrangement then
        # sizes its buffer from ``target_frames``, so a start past it makes
        # ``out[start:start + seg_len]`` shorter than the chunk being summed
        # into it — a numpy broadcast ValueError, not a readable error about
        # placement.
        (1, -5.0, 4.0, "linear", 30, 800.0),
        (1, -5.0, 4.0, "exp", 30, 0.0),
        (1, -5.0, 4.0, "log", 30, 0.0),
        (2, -3.0, 6.0, "linear", 60, 400.0),
        (4, -10.0, 15.0, "exp", 120, 200.0),
    ],
    ids=["defaults", "repro-linear", "repro-exp", "repro-log",
         "wide-gap-linear", "wide-gap-exp"],
)
def test_nothing_starts_past_the_target(
        seg_seconds, gap_start_s, gap_end_s, gap_curve, target_s, crossfade_ms):
    """No placement may start at or past ``target_frames``.

    ``render_arrangement`` sizes its output buffer from ``target_frames``, so
    a placement starting at or past it does not just contribute audio beyond
    the mix's nominal length — depending on how far past, it can make the
    buffer slice ``render_arrangement`` writes into shorter than the chunk
    being summed in, which numpy reports as a bare broadcast-shape
    ``ValueError`` with no mention of a placement or a plan.

    Only the ``defaults`` case was ever exercised here before: at zero gaps
    every stride is ``seg_len - xfade <= seg_len``, so a position computed
    from an in-range one is always still in range, and the loop that lays
    positions out could not overshoot no matter how it was written. The
    other cases use gap arcs where the stride is *not* bounded by the
    segment length — the exact shape a config needs to reach the bug this
    pins down, confirmed by sweeping segment lengths 1-8s, gaps -30s..120s,
    all three curves and several targets/crossfades against this same
    assertion."""
    seg = SegmentInfo("song-1", 0, SR * seg_seconds)
    cfg = _cfg(gap_start_s=gap_start_s, gap_end_s=gap_end_s, gap_curve=gap_curve)
    cfg.output.cycle_crossfade_ms = crossfade_ms
    target = SR * target_s
    plan = plan_arrangement([seg], cfg, target, SR)
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


def test_the_densest_frame_is_the_start_when_nothing_overlaps():
    """At default config every consecutive pair overlaps by exactly the
    crossfade width — a plain seam, blended by ``render_arrangement`` into
    one voice, not summed into two. ``densest_frame`` must not mistake that
    geometric overlap for real concurrency, or it would move off frame 0 on
    every default-configured mix, gap or no gap."""
    from sleepmix.arrangement import densest_frame
    from sleepmix.config import StemDecayConfig

    plan = plan_arrangement([_seg()], _cfg(), SR * 60, SR)
    assert densest_frame(plan, StemDecayConfig(), _DEFAULT_XFADE) == 0


def test_the_densest_frame_moves_when_repeats_stack():
    """Two near-fresh repeats sounding together beat one fresh repeat alone.

    The gap here (-3.0s) overlaps repeats by far more than the default
    crossfade (``_DEFAULT_XFADE``, well under a second), so this is genuine
    additive stacking, not an ordinary seam. Asserted with
    ``concurrent_placements``, not ``Arrangement.at`` (geometric containment)
    — this test's whole subject is that geometric containment is the wrong
    notion of concurrency, so checking the count with it would let a
    regression back to counting every seam as two voices pass silently: a
    ``densest_frame`` that used ``Arrangement.at`` again would still find
    >= 2 placements there by ``plan.at``'s count, even where
    ``concurrent_placements`` finds only 1."""
    from sleepmix.arrangement import concurrent_placements, densest_frame
    from sleepmix.config import StemDecayConfig

    plan = plan_arrangement(
        [_seg()], _cfg(gap_start_s=-3.0, gap_end_s=-3.0), SR * 60, SR)
    frame = densest_frame(plan, StemDecayConfig(), _DEFAULT_XFADE)
    assert frame > 0
    assert len(concurrent_placements(plan, frame, _DEFAULT_XFADE)) >= 2


def test_the_densest_frame_stays_at_the_start_when_the_amplitude_arc_rises():
    """A rising amplitude arc must not send the calibration to the far end.

    ``amp_start_db`` and ``amp_end_db`` are two independent sliders over the
    same −60…0 range, so ``amp_start_db < amp_end_db`` is one drag away from
    any stock config — and it used to invert this ranking outright.
    ``decay_amplitude_proxy`` returned ``db_to_amp(amp_start_db)`` at progress
    0 where ``apply_decay`` actually applies nothing at all, so the first
    repeat was scored as the *quietest*, the last one won, and
    ``preview.master_gain`` measured a window from the wrong end of the arc.
    Measured end to end at the time: +3.85 dB on a stock ``MixConfig`` with
    the arrangement untouched.

    At the default zero gap every pair of placements is an ordinary seam, so
    exactly one placement is concurrent everywhere and this is a pure test of
    the ranking — nothing about stacking is involved."""
    from sleepmix.arrangement import densest_frame
    from sleepmix.config import StemDecayConfig

    rising = StemDecayConfig(amp_start_db=-30.0, amp_end_db=-16.0)
    plan = plan_arrangement([_seg()], _cfg(), SR * 60, SR)
    assert len(plan.placements) > 1, "a single placement would make this vacuous"
    assert densest_frame(plan, rising, _DEFAULT_XFADE) == 0


def test_the_amplitude_proxy_is_untouched_at_progress_zero():
    """The proxy models ``apply_decay``, which does nothing at progress 0.

    ``apply_decay`` short-circuits on ``progress <= 0`` and returns the loop
    untouched, so the amplitude in effect on the first repeat is 1.0 and
    ``amp_start_db`` is never applied to it. Asserted against the literal
    1.0 rather than against anything derived from ``amp_start_db``, because
    the whole failure mode was the proxy agreeing with the *settings* instead
    of with the *code*.

    Both arcs are checked on purpose. The falling one passed before this was
    fixed too — ``db_to_amp(0.0)`` is 1.0 — which is exactly why the defect
    survived: at every default config the wrong expression returned the right
    number. Only the rising arc tells the two apart."""
    from sleepmix.arrangement import decay_amplitude_proxy
    from sleepmix.config import StemDecayConfig

    falling = StemDecayConfig(amp_start_db=0.0, amp_end_db=-16.0)
    rising = StemDecayConfig(amp_start_db=-30.0, amp_end_db=-16.0)
    assert decay_amplitude_proxy(0.0, falling) == 1.0
    assert decay_amplitude_proxy(0.0, rising) == 1.0
    # …and disabled decay is untouched everywhere, as it always was.
    assert decay_amplitude_proxy(0.5, StemDecayConfig(enabled=False)) == 1.0


def test_the_amplitude_proxy_is_the_decibel_arc_past_progress_zero():
    """Past 0 the proxy is the arc itself, checked against arithmetic.

    Hand-computed rather than re-derived from ``lerp``/``db_to_amp``/
    ``shape_progress``: half way along a linear arc from 0 dB to −12 dB is
    −6 dB, and −6 dB is ``10 ** (-6/20)``. An ``exp`` curve squares the
    progress, so half way along that one is a quarter of the way along the
    arc — −3 dB. Nothing here calls the shaping helpers the function under
    test calls, so a proxy that stopped shaping, stopped interpolating, or
    collapsed to a constant fails here rather than agreeing with itself."""
    from sleepmix.arrangement import decay_amplitude_proxy
    from sleepmix.config import StemDecayConfig

    linear = StemDecayConfig(curve="linear", amp_start_db=0.0, amp_end_db=-12.0)
    assert decay_amplitude_proxy(0.5, linear) == pytest.approx(
        10 ** (-6.0 / 20.0), rel=1e-12)
    assert decay_amplitude_proxy(1.0, linear) == pytest.approx(
        10 ** (-12.0 / 20.0), rel=1e-12)

    eased = StemDecayConfig(curve="exp", amp_start_db=0.0, amp_end_db=-12.0)
    assert decay_amplitude_proxy(0.5, eased) == pytest.approx(
        10 ** (-3.0 / 20.0), rel=1e-12)


def test_concurrent_amplitude_combines_as_root_sum_square():
    """The combining rule, pinned against numbers rather than against itself.

    Root-sum-square is the single most expensive decision on this branch —
    it cost three rounds of measurement against real ``render_arrangement``
    output, and it shipped as a fix for a +17.7 dB error that a plain sum
    produced on broadband material. Nothing caught reverting it: the only
    test that touched this recomputed the expected value by calling this very
    function, so a mutation moved both sides of the comparison together.

    So the expected values below are arithmetic, written out: two equally
    loud voices combine to ``sqrt(2)``, four to ``sqrt(4) == 2``, and a full
    voice beside a half-amplitude one to ``sqrt(1 + 0.25)``. A plain sum
    would give 2, 4 and 1.5 — every one of them distinguishable here."""
    from sleepmix.arrangement import concurrent_amplitude
    from sleepmix.config import StemDecayConfig

    off = StemDecayConfig(enabled=False)

    def voices(n, progress=0.0):
        return [Placement("s", 0, 0, progress, SR) for _ in range(n)]

    assert concurrent_amplitude(voices(1), off) == pytest.approx(1.0, rel=1e-12)
    assert concurrent_amplitude(voices(2), off) == pytest.approx(2 ** 0.5, rel=1e-12)
    assert concurrent_amplitude(voices(4), off) == pytest.approx(2.0, rel=1e-12)

    # One fresh voice (untouched, amplitude 1.0) beside one fully decayed to
    # −6.0206 dB, which is exactly half amplitude.
    half = StemDecayConfig(curve="linear", amp_start_db=0.0,
                           amp_end_db=-6.020599913279624)
    mixed = [Placement("s", 0, 0, 0.0, SR), Placement("s", 0, 0, 1.0, SR)]
    assert concurrent_amplitude(mixed, half) == pytest.approx(
        (1.0 + 0.25) ** 0.5, rel=1e-9)
