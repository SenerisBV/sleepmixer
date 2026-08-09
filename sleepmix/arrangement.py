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

from .config import MixConfig, NothingToRender, StemDecayConfig
from .util import db_to_amp, lerp, shape_progress

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


class MalformedArrangement(ValueError):
    """A placement does not fit the buffer a renderer would build for it.

    ``plan_arrangement`` is not supposed to produce this — its own stopping
    rule keeps every ``start_frame`` short of ``target_frames`` — but
    ``render_arrangement`` accepts any ``Arrangement``, including one built
    by hand (a test) or by a future planner that gets the same arithmetic
    wrong again. A ``ValueError`` so a caller that only knows "this config
    produced a bad render" handles it with everything else in the DSP; its
    own type, and a message naming the placement and why, so the actual
    cause reads directly instead of surfacing several frames later as a
    numpy broadcast-shape error with no mention of a plan."""


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

    **A position is only laid down while it is still short of the target**
    (``while pos < target_frames``), not merely computed and appended before
    that gets checked. At zero gaps every stride is ``seg.n_frames - xfade``,
    which is at most ``seg.n_frames``, so a position computed from one that
    was in range is always still in range — the two versions of this loop
    cannot be told apart there, which is why that case alone (the only one
    the tests exercised until now) never showed the difference. Once the gap
    arc goes positive the stride is not bounded by the segment length at
    all, and one stride can leap clean past whatever is left of the target.
    Appending that position anyway used to hand ``render_arrangement`` a
    placement starting at or past ``target_frames``; sized from
    ``target_frames``, its buffer then has no room for the write, which
    surfaces as a bare numpy broadcast ``ValueError`` rather than anything
    that names a placement or a plan. Dropping that position instead is the
    right call, not a workaround: a repeat that would only start after the
    mix has already ended contributes nothing to it. The loop always lays
    down at least one position when ``target_frames > 0`` (``pos`` starts at
    ``0``, which is in range whenever the target is), so this cannot itself
    produce the empty-plan case — that is still exactly
    ``target_frames <= 0``, guarded below.

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
    while pos < target_frames:
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


def decay_amplitude_proxy(progress: float, decay: StemDecayConfig) -> float:
    """How loud a placement at ``progress`` is, amplitude-fade only.

    Not a measurement of what the placement actually sounds like — decay also
    filters, punches holes, drops out and adds noise, none of which this
    accounts for. It exists only to *rank and weight* placements relative to
    one another, which is all ``densest_frame`` and ``preview.master_gain``
    ask of it. Shared between the two rather than duplicated so they cannot
    silently diverge on what "louder" means."""
    if not decay.enabled:
        return 1.0
    shaped = shape_progress(progress, decay.curve)
    return db_to_amp(lerp(decay.amp_start_db, decay.amp_end_db, shaped))


def _effective_spans(plan: Arrangement, xfade: int) -> list[tuple[int, int]]:
    """``(start, effective_end)`` per placement, index-aligned with
    ``plan.placements``.

    Plain geometric containment (``Arrangement.at``) is the wrong notion of
    "sounding" for this purpose: a repeat handing over to the next always
    geometrically overlaps it by exactly the crossfade width, at *every*
    config, gap or no gap — ``plan_arrangement``'s stride is
    ``seg.n_frames - xfade + gap_frames``, so at the default zero gap
    consecutive placements overlap by exactly ``xfade``. That overlap is
    ``equal_power_crossfade``d by ``render_arrangement`` into one blended
    voice, not summed into two, and a handover reading as "two things
    sounding at once" would defeat the whole reason that crossfade exists.

    So a seam is deliberately *not* counted as concurrency here. Only overlap
    *beyond* the crossfade is genuine stacking — the same
    ``0 < overlap <= xfade`` test ``render_arrangement`` already uses to
    choose between its crossfade branch and its additive branch, mirrored
    exactly rather than re-derived, so the two cannot silently disagree about
    which case a given pair of placements is in. Where it's a seam, this
    placement's *effective* end is trimmed to the next placement's start —
    its tail is folded into the blend and must not be double-counted. Where
    it's real stacking (or no overlap at all), the effective end is the real
    one. At default config every pair is a seam, so the effective spans tile
    the timeline with no gaps and no doubling — this is the property that
    keeps ``densest_frame`` landing on frame 0 there, exactly as it did
    before this function existed."""
    placements = plan.placements
    spans: list[tuple[int, int]] = []
    for i, p in enumerate(placements):
        real_end = p.start_frame + p.n_frames
        if i + 1 < len(placements):
            nxt = placements[i + 1]
            overlap = real_end - nxt.start_frame
            end = nxt.start_frame if 0 < overlap <= xfade else real_end
        else:
            end = real_end
        spans.append((p.start_frame, end))
    return spans


def concurrent_placements(plan: Arrangement, frame: int, xfade: int) -> list[Placement]:
    """Every placement genuinely sounding as its own voice at ``frame``.

    Not ``Arrangement.at``: that is pure geometric containment, which counts
    an ordinary crossfade seam as two voices when ``render_arrangement``
    blends it into one — see ``_effective_spans`` for why that distinction
    matters and how it's drawn. Shared by ``densest_frame`` (ranks frames by
    this) and ``preview.master_gain`` (weighs the frame ``densest_frame``
    picks by this same set), so the ranking and the scaling can never
    disagree about which placements they mean by "concurrent"."""
    spans = _effective_spans(plan, xfade)
    return [p for p, (start, end) in zip(plan.placements, spans)
            if start <= frame < end]


def concurrent_amplitude(placements: list[Placement], decay: StemDecayConfig) -> float:
    """Root-sum-square of ``decay_amplitude_proxy`` across ``placements``.

    Not a plain sum. A plain sum assumes the concurrent repeats are
    *coherent* — in phase, adding sample for sample, like duplicates of one
    signal — and they are much closer to independent sources: the same loop
    at different decay stages, offset in time by a full stride. Measured
    against a real local sum of decayed placements across several content
    types and concurrency counts, a plain sum over-predicted broadband and
    percussive content badly enough to push the derived gain several dB
    *below* where it should sit — worse than the ~4 dB defect this whole
    module exists to fix, just pointed the other way. Root-sum-square is the
    standard estimate for how independent sources combine and measured
    closer to those same renders, though not uniformly: it still under-
    predicts on strongly tonal, near-periodic content, which is more
    phase-coherent than the independent-source assumption behind it. See
    ``preview.master_gain``'s docstring for the actual measured numbers, both
    directions, and why the residual is tolerated rather than eliminated.
    With exactly one placement this is identical to that placement's own
    ``decay_amplitude_proxy``, so the no-stacking case — every default
    config — is unaffected."""
    return sum(decay_amplitude_proxy(p.decay_progress, decay) ** 2
               for p in placements) ** 0.5


def densest_frame(plan: Arrangement, decay: StemDecayConfig, xfade: int) -> int:
    """The frame where the most amplitude is likely to coincide.

    ``preview.master_gain`` measures one window and used to assume it was the
    first: decay only removes energy, so the peak fell monotonically and
    iteration 0 was the loudest thing that module could produce. Overlapping
    repeats (a negative gap large enough to exceed the crossfade width) break
    that — two near-fresh repeats sounding together beat one fresh repeat
    alone, and a gain calibrated at frame 0 leaves the real peak above
    target.

    ``xfade`` is the crossfade width in frames (``arrangement.xfade_frames``
    is the single source of that clamp; callers should use it rather than
    re-deriving one). It exists so concurrency can be measured over
    *effective* spans rather than raw geometric ones — see
    ``concurrent_placements`` and ``_effective_spans`` for why an ordinary
    seam must not be counted as two voices.

    The proxy below only has to *rank* candidates; the level is still
    measured by rendering a real window (see ``master_gain``). Candidates are
    the placement starts themselves, because the combined concurrent
    amplitude only changes where a placement's effective span begins or
    ends, and every effective span starts at its placement's own start.
    Ranked by ``concurrent_amplitude`` (root-sum-square, not a plain sum —
    see that function) so the frame this picks agrees with how
    ``master_gain`` weighs it; the two must use the same combining rule or
    the frame that "wins" and the scaling applied to it stop meaning the same
    thing."""
    best_frame, best = 0, -1.0
    for candidate in plan.placements:
        frame = candidate.start_frame
        total = concurrent_amplitude(
            concurrent_placements(plan, frame, xfade), decay)
        if total > best:
            best, best_frame = total, frame
    return best_frame
