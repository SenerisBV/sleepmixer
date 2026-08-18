"""The pair, and the two things one mechanism buys.

A ghost is its own Voice rather than a mode of one. That single choice gives
the birth ratio (the relative gain of a co-located pair) and ghosts that
outlive their source (the same pair with different lifetimes) without a second
mechanism for either.
"""
import math

import pytest

from sleepmix.night.clock import arc_at
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    MAX_SOURCE_RATIO, MIN_AUDIBLE_RATIO, ROOT_DESCENT_SEMITONES, TEXTURES,
    _pitch_hz, is_ghost, plan_voices, schedule_sources, source_ratio,
    stage_at,
)
from sleepmix.night.sources import SourceProfile

SR = 22050
NIGHT_S = 8 * 3600.0


def _profile(name, pitches=(55.0, 82.5)):
    return SourceProfile(source_id=name, source_path=f"/songs/{name}.flac",
                         loop_paths=(f"/{name}-0.wav",
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


def test_with_no_sources_the_walk_takes_one_index_per_voice():
    """The test above only proves the new code is reproducible against
    itself — it would pass just as well if every voice were silently
    keyed on index 0, 2, 4, ... instead of 0, 1, 2, .... That is exactly
    a bug pairing brought in: ``Voice.key`` (and so every voice's own
    material and decay noise, drawn from ``iteration_rng(seed, key,
    ...)``) is derived from ``index`` alone, so an unconditional stride
    of two — reserving a ghost slot even on a night with no ghosts to
    reserve one for — would still change every voice's identity, even
    though the *code path* taken is otherwise exactly Phase 1's. That
    silently moved Phase 1's seed-parameterised clipping tests in
    ``tests/test_night_stream.py`` before the stride was made a
    per-context constant decided from ``ctx.sources``. Pin the walk's
    stride directly: with no sources, voice keys must be consecutive
    from zero, which is the observable form of "Phase 1 unchanged"
    available from inside ``plan.py`` alone."""
    ctx = _context()
    keys = [v.key for v in _night(ctx)]
    assert keys
    assert keys == [f"night:voice:{i}" for i in range(len(keys))]


def test_with_no_sources_the_walk_is_byte_identical_to_phase_one():
    """The two tests above cannot catch a change that shifts *timing*
    rather than *keys*: both compare the new code against itself, so a
    bug that moves both calls equally is invisible to them. This is a
    golden-value test instead — a real reference, not the new code
    checked against itself.

    The reference values below are Phase 1's actual output, captured by
    checking out ``sleepmix/night/plan.py`` at commit 75eb039 (the tip of
    this branch immediately before pairing began) and running
    ``plan_voices`` for seed 1, no sources, an eight-hour night, at
    SR=22050 — exactly this file's own ``_context()``/``_night()``. That
    run produced 81 voices; birth_frame and pitch_hz for the first eight
    are pinned here.

    This test is deliberately brittle: a pairing regression it would have
    caught in review drew four pair-only values (loop pick, ghost-pitch
    pick, outlive roll, outlive factor) unconditionally, even with no
    sources to spend them on. That did not change any voice's *key* — the
    stride fix already handled that — but it shifted where the birth-gap
    draw lands in the per-step generator's own state, so ``gap_s``, the
    cursor, and every voice after the first came out different: 82
    voices instead of 81, and voice index 1 born at frame 1116270 instead
    of the correct 1280197 (which is the value pinned below, and the two
    were printed the wrong way round here until the whole-branch review
    caught it — a false statement inside the one deliberately-brittle
    test on the branch). If a future change moves Phase 1's audio
    again, this test should fail and someone should look at it on
    purpose, not have it pass by construction."""
    ctx = _context()
    voices = _night(ctx)
    assert len(voices) == 81

    # (index, birth_frame, n_frames, pitch_hz, texture) — Phase 1's own
    # output at commit 75eb039, seed 1, no sources, SR=22050, 8h night.
    golden = [
        (0, 0, 4865954, 185.010958, "drone"),
        (1, 1280197, 3122900, 69.292738, "drone"),
        (2, 3281633, 3315522, 69.280124, "drone"),
        (3, 5024001, 3355252, 82.375360, "drone"),
        (4, 6854085, 4186454, 92.447826, "noiseband"),
        (5, 8459417, 3392155, 184.868655, "noiseband"),
        (6, 9972923, 4022475, 123.368039, "noiseband"),
        (7, 12164073, 3127451, 69.224173, "drone"),
    ]
    for (index, birth_frame, n_frames, pitch_hz, texture), voice in zip(
            golden, voices[:len(golden)]):
        assert voice.index == index
        assert voice.birth_frame == birth_frame
        assert voice.n_frames == n_frames
        assert voice.pitch_hz == pytest.approx(pitch_hz, abs=1e-4)
        assert voice.texture == texture


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
    """The fold band is 55-110 Hz and the seed's own root choices are
    55.00-82.41 Hz, both inside `20 < pitch < 130`, so that range cannot
    distinguish a ghost pitch from a seed pitch. Assert instead that the
    ghost sits within a few cents of an actual member of its source's
    pitch_set, after accounting for the same root descent every other
    voice gets."""
    pitches = (55.0, 82.5)
    ctx = _context([_profile("a", pitches)])
    night_frames = int(NIGHT_S * SR)
    ghosts = [v for v in _night(ctx) if is_ghost(v)]
    assert ghosts
    for ghost in ghosts:
        elapsed = min(max(ghost.birth_frame / night_frames, 0.0), 1.0)
        descent = -ROOT_DESCENT_SEMITONES * elapsed * 100.0
        expected = [_pitch_hz(hz, descent) for hz in pitches]
        closest = min(expected, key=lambda e: abs(ghost.pitch_hz - e))
        cents = abs(1200.0 * math.log2(ghost.pitch_hz / closest))
        assert cents < 1.0, (
            f"ghost pitch {ghost.pitch_hz} is {cents} cents from the "
            f"nearest source pitch {closest}, not a member of {pitches}")


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


def test_a_loopless_source_does_not_crash_and_produces_no_source_voices():
    """Named hazard: every length can be zero, including ``loop_paths``.
    A profile with pitches but no loops (hand-edited, or a profile whose
    loop files went missing after being written) must not raise dividing
    ``loop_pick % len(profile.loop_paths)`` by zero, and correctly never
    emits a ``"source"`` voice for material it does not have."""
    loopless = SourceProfile(source_id="a", source_path="/songs/a.flac",
                             loop_paths=(), loop_frames=(),
                             pitch_set=(55.0, 82.5), sr=44100)
    ctx = _context([loopless])
    voices = _night(ctx)  # must not raise
    assert not any(v.texture == "source" for v in voices)
    assert any(is_ghost(v) for v in voices)


# -- outliving ---------------------------------------------------------
def test_every_handover_is_covered():
    """The seam between two sources is hidden by the mechanism already
    chosen, not by a crossfade added for the purpose.

    Originally asserted a *ghost* specifically crosses every seam. That
    assumed the cover must be a ghost, which is false whenever the
    outgoing source is pitchless (ordinary, not exceptional — see
    ``pitch.py``): no ghost is ever emitted for such a source, so a
    ghost-only check would have missed 25 of 59 seeds producing at least
    one bare handover out of a (pitchless, pitched, pitched) rotation.
    The cover is generalised to whichever voice this step emitted —
    ghost, in-progress source loop, or the synthesis fallback — is
    already longest-lived; this test now checks that *something* crosses
    every seam, not that a ghost specifically does. See
    ``test_a_handover_out_of_a_pitchless_source_is_still_covered`` for the
    case this generalisation exists for."""
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abc")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    voices = _night(ctx)
    for stage in schedule[:-1]:
        crossing = [v for v in voices
                    if v.birth_frame < stage.end_frame
                    and v.birth_frame + v.n_frames > stage.end_frame]
        assert crossing, f"handover at {stage.end_frame} is bare"


def test_a_handover_out_of_a_pitchless_source_is_still_covered():
    """Critical, reviewer-found: a pitchless source is ordinary, not
    exceptional — Task 1 tried twice to reject non-tonal material and both
    attempts failed, so ``pitch.py`` documents that a real ambient or
    percussion-led recording legitimately has no detectable pitches. No
    ghost is ever emitted for such a source (the ghost branch is gated on
    ``profile.pitch_set``), so with the cover living only on the ghost, a
    pitchless source in any non-final rotation slot left every handover
    out of its stage bare. A sweep of seeds 1-59 with (pitchless, pitched,
    pitched) found 25 of 59 producing at least one bare seam.

    Fixed by generalising the cover to whichever voice a step actually
    emits — ghost, in-progress source loop, or the synthesis fallback —
    stretching the longest-lived of them, not assuming a ghost exists. A
    source loop occasionally sustaining past its stage is the same
    gesture the design already sanctions for a ghost outliving its
    source.

    Swept across all 59 seeds rather than pinned to one: the 25-of-59
    failure rate for the un-fixed code means a single lucky seed would be
    an unreliable guard, passing by chance rather than by the fix."""
    bare_by_seed = {}
    for seed in range(1, 60):
        sources = [_profile("pitchless", ()), _profile("b", (56.0,)),
                  _profile("c", (80.0,))]
        ctx = _context(sources, seed=seed)
        schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
        voices = _night(ctx)
        bare = [stage.end_frame for stage in schedule[:-1]
               if not any(v.birth_frame < stage.end_frame
                          and v.birth_frame + v.n_frames > stage.end_frame
                          for v in voices)]
        if bare:
            bare_by_seed[seed] = bare
    assert not bare_by_seed, f"bare handovers by seed: {bare_by_seed}"


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


def test_with_sources_every_step_still_reserves_a_pair_slot():
    """The other half of the stride pin: with sources in play, the walk
    goes back to advancing by two, since that is what actually reserves
    ``index + 1`` for a ghost that may or may not be born. Every step
    emits exactly one non-ghost voice (the source, or the pitchless-source
    fallback) at the step's own ``index`` — never at ``index + 1`` — so
    the set of non-ghost indices is exactly the even numbers from zero,
    one per step, with no gaps and no repeats."""
    ctx = _context([_profile("a")])
    primary_indices = sorted(v.index for v in _night(ctx) if not is_ghost(v))
    assert primary_indices
    assert primary_indices == list(range(0, 2 * len(primary_indices), 2))


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


# -- regression: bugs found in the plan's draft ------------------------
def test_the_cover_reaches_its_full_distance_past_every_handover():
    """A seam is not merely *crossed* — something reaches
    ``HANDOVER_COVER_S`` past it, so the incoming source has clearly
    arrived before the covering voice lets go.

    This replaces an earlier test that pinned the same code by a
    different route: it looked for a crossing voice whose required
    ``reach`` exceeded the ``MAX_VOICE_S * 3`` cap, proving the cap was
    applied *before* the cover rather than after. That case is no longer
    reachable, and deliberately so. ``reach`` is
    ``(seam - cursor) + HANDOVER_COVER_S``, and ``SEAM_APPROACH_S`` now
    bounds ``seam - cursor`` at 15 s, so ``reach`` cannot exceed 105 s
    against a 720 s cap — the ordering the old test guarded has become
    unobservable because the quantity it guarded is bounded two orders of
    magnitude below the cap. Rather than keep an assertion that could only
    pass vacuously (``assert triggered`` would fail, which is how this was
    noticed), the guard moves to the property that survives: whatever the
    cover does, it delivers the full ``HANDOVER_COVER_S`` past the seam.

    Checked over every genuine handover of several seeds, not one, per
    the standing rule that a fix justified by N measurements is asserted
    over N.
    """
    from sleepmix.night.plan import HANDOVER_COVER_S

    cover = int(HANDOVER_COVER_S * SR)
    checked = 0
    for seed in (1, 2, 5, 11, 29):
        ctx = _context([_profile(n, (55.0 + i * 2,))
                        for i, n in enumerate("abc")], seed=seed)
        schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
        voices = _night(ctx)
        for i in range(len(schedule) - 1):
            if schedule[i].source_index == schedule[i + 1].source_index:
                continue
            seam = schedule[i].end_frame
            crossing = [v for v in voices if v.birth_frame < seam
                        and v.birth_frame + v.n_frames > seam]
            assert crossing, f"seed {seed}: handover at {seam} is bare"
            furthest = max(v.birth_frame + v.n_frames for v in crossing)
            checked += 1
            assert furthest >= seam + cover, (
                f"seed {seed}: the cover at {seam} stops "
                f"{(seam + cover - furthest) / SR:.1f}s short of the full "
                f"{HANDOVER_COVER_S}s")
    assert checked > 60, (
        f"only {checked} genuine handovers were checked; this test has "
        "stopped exercising what it claims to")


def test_no_voice_ever_exceeds_the_stated_ceiling():
    """Critical, reviewer-found: the handover cover had no upper bound.

    ``reach = max(seams) - cursor + HANDOVER_COVER_S`` was applied after
    every cap, deliberately — but ``max(seams) - cursor`` was bounded only
    by the birth gap, which at the sparsest late-night density reaches
    ~980 s. Measured at 44.1 kHz across 119 seeds: the longest voice of a
    night was 240.0 s with no sources and **943.9 s with two or more**,
    and rendering one cost a peak RSS of **10.3 GB** against a 0.31 GB
    output buffer. And ``stream.summed``'s per-voice ``except Exception``
    catches ``MemoryError``, so an OOM drops the voice — the very voice
    extended to cover the seam.

    ``MAX_VOICE_TOTAL_S`` is the bound the fix earns; see its comment in
    ``plan.py`` for why it is stated as a sum of two things that do not
    actually compose. Swept wide on purpose: 63 of those 119 seeds
    breached the ceiling, so a single seed would be a coin toss rather
    than a guard, and the breach only appears at two or more sources, so
    the source count is swept too — with no sources at all the longest
    voice is 240.0 s and nothing here would ever fire.
    """
    from sleepmix.night.plan import MAX_VOICE_TOTAL_S

    ceiling = int(MAX_VOICE_TOTAL_S * SR)
    worst = (0, None)
    for n_sources in (0, 1, 2, 3, 6):
        sources = [_profile(chr(97 + i), (55.0 + i * 4.0, 82.0 + i * 3.0))
                   for i in range(n_sources)]
        for seed in range(1, 120):
            for voice in _night(_context(sources, seed=seed)):
                if voice.n_frames > worst[0]:
                    worst = (voice.n_frames, (n_sources, seed, voice.index))
                assert voice.n_frames <= ceiling, (
                    f"{n_sources} sources, seed {seed}: voice "
                    f"{voice.index} is {voice.n_frames / SR:.1f}s, past the "
                    f"{MAX_VOICE_TOTAL_S}s ceiling")
    assert worst[0] > 0


def test_a_voice_is_born_within_reach_of_every_handover():
    """The clamp itself, rather than its consequence.

    The ceiling test above would also pass if someone bounded the cover by
    truncating it — which would put the bare seam straight back. What
    actually makes the bound safe is that the *walk* stops short of a
    seam, so a voice is born ``SEAM_APPROACH_S`` before it and covers it
    from close range. Assert that directly: every genuine handover has a
    voice born in the ``SEAM_APPROACH_S`` before it.

    Swept over source counts because with one source there are no genuine
    seams at all, and over seeds because at density 1.0 an unclamped walk
    would land close to a seam by luck often enough for one seed to pass.
    """
    from sleepmix.night.plan import SEAM_APPROACH_S

    approach = int(SEAM_APPROACH_S * SR)
    seams_checked = 0
    for n_sources in (2, 3, 6):
        sources = [_profile(chr(97 + i), (55.0 + i * 4.0, 82.0 + i * 3.0))
                   for i in range(n_sources)]
        for seed in range(1, 30):
            ctx = _context(sources, seed=seed)
            schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
            births = {v.birth_frame for v in _night(ctx)}
            for i in range(len(schedule) - 1):
                if schedule[i].source_index == schedule[i + 1].source_index:
                    continue
                seam = schedule[i].end_frame
                seams_checked += 1
                assert any(seam - approach <= b < seam for b in births), (
                    f"{n_sources} sources, seed {seed}: nothing is born in "
                    f"the {SEAM_APPROACH_S}s before the handover at {seam}, "
                    "so whatever covers it is covering from an unbounded "
                    "distance")
    assert seams_checked > 100


def test_a_gap_that_skips_a_whole_stage_still_covers_every_seam_it_skipped():
    """Named hazard: does the handover condition fire for every seam,
    including one falling between two births with no voice born near it?
    Force very short stages (by monkeypatching STAGE bounds is out of
    scope here) is not needed: the walk's own birth-gap draws are already
    sparse enough, late in an eight-hour night, to skip a stage boundary
    outright. Assert every seam is still covered regardless."""
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abcdefgh")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    voices = _night(ctx)
    bare = []
    for stage in schedule[:-1]:
        crossing = [v for v in voices
                    if v.birth_frame < stage.end_frame
                    and v.birth_frame + v.n_frames > stage.end_frame]
        if not crossing:
            bare.append(stage.end_frame)
    assert not bare, f"bare handovers at {bare}"


# -- the seam gate: a same-source boundary is not a handover -----------
#
# ``schedule_sources`` still emits a stage boundary every time a stage
# ends, even with one source (the walk keeps advancing off the
# stage-length draw alone, since the nearest-pitch selection rule never
# runs with nothing to choose between). Before this fix, ``plan_voices``
# treated every one of those boundaries as a seam, which fired the
# handover cover on stretches of a solo night with nothing to cover:
# measured at 17.9% of walk steps, one source voice stretched past 800s
# purely by it, and the ghost's own ``OUTLIVE_CHANCE`` flourish
# suppressed (gated on ``not seams``) for most of the night even though
# nothing needed covering.

def test_a_single_source_produces_no_spurious_seams():
    """A boundary from a source back to itself is not a handover: with
    one source every stage still names the same ``source_index``, so no
    walk step should ever treat itself as crossing a seam.

    Two behavioural proxies, since ``seams`` is a local variable inside
    ``plan_voices`` and not itself observable from outside:

    1. No ``"source"``-texture voice should ever be stretched past its
       natural ``MAX_VOICE_S`` cap — the handover-cover step is the only
       thing in this module that can push a source voice past that cap,
       and with no genuine seam it should never fire. The reported
       regression measured a source stretched to 839.3s this way, nearly
       3.5x the 240s cap.
    2. Late in the night the birth ratio favors the ghost heavily
       (elapsed near 1.0 => ``source_ratio`` near 0.0), so ghosts should
       actually show up there. Before the fix, ``not seams`` was false at
       most steps even with one source, which suppressed
       ``OUTLIVE_CHANCE`` and, combined with the cover itself nearly
       always picking the source side of a tied pair, left long stretches
       source-only.
    """
    from sleepmix.night.plan import MAX_VOICE_S

    ctx = _context([_profile("solo")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    assert len(schedule) > 1, (
        "sanity: a solo night should still cross several stages")
    assert len({s.source_index for s in schedule}) == 1, (
        "sanity: every stage should name the same, only source")

    voices = _night(ctx)
    for v in voices:
        if v.texture == "source":
            assert v.n_frames <= int(MAX_VOICE_S * SR), (
                f"voice {v.index} is {v.n_frames / SR:.1f}s, past "
                f"MAX_VOICE_S={MAX_VOICE_S}s — stretched by a spurious "
                "self-handover cover")

    late_start = int(0.9 * NIGHT_S * SR)
    late = [v for v in voices if v.birth_frame >= late_start]
    assert late, "sanity: the night should still have voices this late"
    ghosts_late = [v for v in late if is_ghost(v)]
    assert ghosts_late, (
        "no ghosts appear in the last tenth of a solo night, where the "
        "birth ratio says they should dominate")


def test_every_genuine_handover_is_still_covered_after_the_seam_gate():
    """Regression guard for the fix itself, not the bug: gating ``seams``
    on ``source_index`` actually changing must not stop excluding the
    spurious boundaries while also excluding real ones. Reuses
    ``test_every_handover_is_covered``'s own shape — three distinct
    sources, so ``schedule_sources``'s nearest-pitch rule changes
    ``source_index`` at every boundary by construction — but derives
    "genuine" the same way the fix does, by comparing ``source_index``
    across the boundary, rather than assuming every boundary in a
    multi-source context is automatically genuine."""
    ctx = _context([_profile(n, (55.0 + i * 2,)) for i, n in enumerate("abc")])
    schedule = schedule_sources(ctx, SR, int(NIGHT_S * SR))
    voices = _night(ctx)
    genuine = [schedule[i] for i in range(len(schedule) - 1)
              if schedule[i].source_index != schedule[i + 1].source_index]
    assert genuine, (
        "sanity: three distinct sources should produce genuine handovers")
    assert len(genuine) == len(schedule) - 1, (
        "sanity: with three distinct sources every boundary should "
        "already be genuine, so this test exercises the same boundaries "
        "test_every_handover_is_covered does")
    for stage in genuine:
        crossing = [v for v in voices
                    if v.birth_frame < stage.end_frame
                    and v.birth_frame + v.n_frames > stage.end_frame]
        assert crossing, f"genuine handover at {stage.end_frame} is bare"


def test_the_moon_still_does_not_move_a_single_birth_with_sources_in_play():
    """The brief's draft drew the interval directly from `intervals`
    (`rng.choice(intervals)`), whose width varies with the moon, rather
    than the fixed-width slot mechanism the already-shipped Phase 1 code
    uses and documents as load-bearing for exactly this property. I kept
    the established mechanism rather than the brief's simplification, for
    consistency with that stated design intent.

    Honesty check on this test: I could NOT get it to fail against the
    brief's simplification. A 6000-trial sweep comparing
    `rng.choice(len(_INTERVALS_CENTS))` against `rng.choice(intervals)`
    directly, for the actual widths in play (4, 5, 6), found the two
    consume numpy's `Generator` state identically every time — so, for
    this numpy version and these widths, the divergence the original
    Phase 1 comment warns about does not appear to be observable. This
    test therefore is NOT proven discriminating; it documents adherence
    to the established pattern rather than a demonstrated regression, and
    is flagged as such in the task report rather than adjusted to look
    more conclusive than it is."""
    profiles = [_profile("a")]
    reference = [(v.index, v.birth_frame, v.n_frames, v.texture)
                 for v in _night(_context(profiles))]
    for phase in (0.0, 0.17, 0.25, 0.75, 0.93, 1.0):
        ctx = NightContext(
            seed=1, night_length_s=NIGHT_S,
            weather=Weather(cloud_cover=0.5, precipitation_mm=0.0,
                            wind_ms=3.0, pressure_hpa=1013.25,
                            pressure_trend_hpa=0.0),
            moon_phase=phase, day_length_h=12.0, sources=tuple(profiles))
        night = [(v.index, v.birth_frame, v.n_frames, v.texture)
                 for v in _night(ctx)]
        assert night == reference, f"moon {phase} moved the night's schedule"


def test_no_source_voice_is_born_once_its_half_of_the_pair_is_inaudible():
    """``MIN_AUDIBLE_RATIO`` gates both halves of the pair, and only the
    ghost's half was covered by a test.

    The source half is gated by ``ratio > MIN_AUDIBLE_RATIO``. Since
    ``source_ratio`` falls linearly from ``MAX_SOURCE_RATIO`` to zero, the
    gate closes at ``elapsed = 1 - MIN_AUDIBLE_RATIO / MAX_SOURCE_RATIO``
    — about 94.1% through the night — after which every voice must be a
    ghost or the synthesis fallback and never a loop played at a gain of
    ``sqrt(0.02)``. Removing that condition was caught by nothing.

    The cutoff is derived from the two constants rather than written as
    0.941, so retuning either moves the test with the code instead of
    against it. Swept over seeds because the late night is sparse enough
    that a single seed can have no births in the window at all — which is
    also why the sanity assertion counts them.
    """
    cutoff = 1.0 - MIN_AUDIBLE_RATIO / MAX_SOURCE_RATIO
    night_frames = int(NIGHT_S * SR)
    late_births = 0
    for seed in range(1, 25):
        ctx = _context([_profile("a"), _profile("b", (58.0, 87.0))], seed=seed)
        for voice in _night(ctx):
            elapsed = voice.birth_frame / night_frames
            if elapsed <= cutoff:
                continue
            late_births += 1
            assert voice.texture != "source", (
                f"seed {seed}: a source voice is born at elapsed "
                f"{elapsed:.3f}, past the point where its own half of the "
                f"pair falls under MIN_AUDIBLE_RATIO={MIN_AUDIBLE_RATIO}")
    assert late_births > 20, (
        f"only {late_births} voices were born past elapsed {cutoff:.3f}; "
        "this test is not reaching the branch it guards")
