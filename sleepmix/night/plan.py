"""Who is born when, and under what ceiling.

This is the inner half of the design's two nested clocks. The arc decides what
the night permits; this decides what actually shows up, and hands each voice a
``StemDecayConfig`` whose *endpoints* are the arc's ceilings at the moment that
voice was born. The voice is then rendered at ``progress = 1.0``, so the
ceiling is not a limit it approaches — it is where it already is. A voice born
at hour six enters dark and quiet and has no way to be anything else.

**No audio is imported here, at all.** ``StemDecayConfig`` is a dataclass and
``iteration_rng`` is arithmetic. That is what lets ``tests/test_night_plan.py``
assert properties of an eight-hour night without rendering a sample, and it is
the same rule ``arrangement.py`` lives by for the same reason.

**One steering input lands here rather than in ``clock.py``.** Moon phase
sets the width of the interval set — the spec's own row for it — and an
interval set is not one of the arc's four descending ceilings, so there is no
field of ``NightArc`` it could have been. ``interval_set`` below carries the
reasoning, including why it is not threaded into ``palette.py``.

**The walk always starts at voice zero**, even when only a ten-second window is
wanted. That looks wasteful and is not: a night holds a few hundred voices and
the walk is arithmetic, so a whole night plans in well under a millisecond.
Starting from zero every time is what makes a window's answer *identical* to
the whole night's answer restricted to that window, which is the property the
block renderer's independence rests on. A cleverer resumable walk would have to
prove that equality; this one cannot fail it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..config import StemDecayConfig
from ..util import iteration_rng, lerp
from .clock import arc_at, NightArc
from .context import NightContext
from .sources import pitch_distance

TEXTURES = ("drone", "noiseband", "source")

# A voice lives minutes, not hours. The floor keeps anything from reading as an
# event; the ceiling keeps a single voice from becoming the whole night.
MIN_VOICE_S = 45.0
MAX_VOICE_S = 240.0

# Spacing between births, before the arc's density thins it out. At density 1.0
# a voice is born every _BIRTH_GAP_MIN_S to _BIRTH_GAP_MAX_S; at density 0.05
# the same range is stretched by _SPARSEST_STRETCH.
_BIRTH_GAP_MIN_S = 20.0
_BIRTH_GAP_MAX_S = 70.0
_SPARSEST_STRETCH = 14.0

# The roots a night may open on — low, and drawn from the seed. All are well
# under 100 Hz because everything above sits on top of them as an interval.
_ROOT_CHOICES_HZ = (55.00, 61.74, 65.41, 73.42, 82.41)

# Cents above the root a voice may sit at. Consonant throughout: unison, major
# second, perfect fourth, perfect fifth, octave, and a fifth above that. No
# thirds — they colour a chord major or minor, and a night should not have a
# mood it is asserting.
#
# Ordered from tightest to widest on purpose: the moon reaches this tuple by
# controlling how much of its *upper end* is available, so a prefix of it is
# always a legal interval set. See ``interval_set``.
_INTERVALS_CENTS = (0, 200, 500, 700, 1200, 1900)

# The fewest intervals a night may draw from — unison, second, fourth, fifth.
# A new moon narrows to exactly these. It is a floor rather than a limit that
# can be reached from below: a set that could empty, or that could be narrowed
# to unison alone, would turn one steering input into the difference between
# music and a single held tone.
_MIN_INTERVAL_WIDTH = 4

# How far the root falls across a whole night. Imperceptible minute to minute,
# unmistakable between 23:00 and 05:00, and the same gesture the decay engine
# already makes in the frequency domain.
ROOT_DESCENT_SEMITONES = 1.0

# How far under the night's level ceiling a voice's tape hiss sits.
#
# ``apply_decay`` adds its noise floor *last* — after the lowpass, after the
# gain — so a fixed value from ``StemDecayConfig``'s defaults is an absolute
# level that the arc cannot touch. Left at the default -42 dB it defeated three
# separate things at once: it was broadband, so it walked straight through the
# brightness ceiling; it was absolute, so a voice born at hour six carried the
# same hiss as one born at hour zero even though everything else about it had
# descended; and it was added after ``palette``'s fade, so a voice's first
# sample stepped from digital silence to audible hiss.
#
# Tying it to ``arc.level_db`` fixes the second of those here and the other two
# are fixed at the ends they belong to (``stream._rendered`` re-fades the whole
# buffer; the brightness ceiling is a spectral property the fade cannot help
# with, but a hiss 40 dB under the tone is quiet enough not to dominate it).
#
# **This is a taste value and nobody has listened to it.** -40 dB below the
# level ceiling was chosen so a fresh voice's hiss sits well under its own
# tone; whether that reads as tape or as nothing at all is a question for ears.
NOISE_BELOW_LEVEL_DB = -40.0

# The most source-derived voice of the night still carries some of its own
# ghost, so the unprocessed loop is never heard alone, at any hour. This is
# the most direct implementation of "clearly music, not identifiable", and it
# is a placeholder nobody has listened to.
#
# **It is a gain ratio, applied after each voice is peak-normalised on its
# own, and not the energy split it reads like.** ``palette.render_voice``
# normalises every voice to its own peak before ``gain`` is applied, so the
# two halves of a pair arrive at the mix with unrelated crest factors — a
# tiled recording is peaky, a drone is not, a noise band is somewhere else
# again — and an equal-power gain pair therefore realises whatever energy
# split those crest factors imply. Measured across ten consecutive real
# pairs: an intended 0.85 realised as anywhere from **0.60 to 0.91**. That is
# also why the 22:30 listening excerpt reads 69/31 against an intended 85/15.
#
# The safety property this constant exists for survives, which is why this is
# documented rather than fixed: the ghost is never *absent*, and at the top of
# the observed spread it is still about -10 dB rather than gone. What does not
# survive is the reading that tuning this number moves the split by a
# predictable amount — it moves it by an amount that depends on the material.
# Moving to RMS normalisation would fix that and would also change every level
# on this branch and invalidate the listening excerpts for a fourth time,
# before anyone has listened to the current ones. It is the top follow-up in
# ``docs/project-state.md``, not a change to make on the way out the door.
MAX_SOURCE_RATIO = 0.85

# Below this a voice in the pair is not worth rendering.
MIN_AUDIBLE_RATIO = 0.05

# A ghost crossing a handover must reach at least this far past it, so the
# seam between two sources is never bare.
HANDOVER_COVER_S = 90.0

# How close before a genuine handover a voice is born, so that the cover
# hiding that seam spans a *bounded* distance rather than an arbitrary one.
#
# The cover stretches whatever a step emits from its own ``cursor`` to past
# the seam, so its length is ``(seam - cursor) + HANDOVER_COVER_S``. Nothing
# bounded ``seam - cursor``: it was whatever birth gap that step happened to
# draw, and at the sparsest late-night density a gap reaches ~980 s. Measured
# at 44.1 kHz over 119 seeds, before this clamp existed: the longest voice of
# a night was 240.0 s with no sources but **943.9 s with two or more**, on 63
# of those 119 seeds, and rendering one cost a peak RSS of **10.3 GB** against
# a 0.31 GB output buffer — ``apply_decay`` holds roughly 34x its input, at
# every length. It compounds, too: ``stream.summed``'s per-voice
# ``except Exception`` catches ``MemoryError``, so an OOM silently drops a
# voice — and the dropped voice is precisely the one that had been extended
# to cover the seam. The audible result is a bare handover plus a
# multi-second stall, in the middle of the night, with nothing said loudly.
#
# So the *walk* is clamped rather than the cover. When a genuine seam lies
# further than this ahead, the step stops short of it, and the voice born
# ``SEAM_APPROACH_S`` before the seam is the one that covers it. The cover
# then spans at most ``SEAM_APPROACH_S + HANDOVER_COVER_S``, whatever the
# density. This is decided from ``schedule``, which is a per-context constant
# fixed for the whole night — the same standing that lets ``stride`` be
# decided once — so it costs nothing in block independence: a window planned
# from any offset walks the identical cursors.
#
# The correctness condition is staying below the *maximum* birth gap
# (~980 s at the sparsest density the walk draws), not the minimum: that is
# what keeps the clamp able to fire at all. Measured at 0.001 s, 1 s, 60 s,
# and 200 s — all above ``_BIRTH_GAP_MIN_S`` — every one still gives zero
# bare seams and zero ceiling breaches; only 1200 s, above the maximum birth
# gap, breaches. Kept under ``_BIRTH_GAP_MIN_S`` (20 s, the smallest gap any
# density can draw) anyway, but that is a nicety rather than a requirement:
# it means the step born before a seam reaches past it on its very next
# draw rather than creeping toward it over several. A placeholder like
# everything around it — but a bounded one.
SEAM_APPROACH_S = 15.0

# Away from a handover, a ghost outliving its source is a flourish rather than
# the rule — a repeated gesture is the failure mode this design worries about
# most. All three are placeholders.
OUTLIVE_CHANCE = 0.15
OUTLIVE_MIN, OUTLIVE_MAX = 1.5, 2.5

# The longest any single voice may be, and the bound the memory cost of a
# night rests on. Two things can lengthen a voice past ``MAX_VOICE_S`` and
# they do not compose: the occasional outliving flourish multiplies a ghost's
# drawn lifetime by at most ``OUTLIVE_MAX``, and the handover cover *replaces*
# a length rather than adding to it, reaching at most ``SEAM_APPROACH_S +
# HANDOVER_COVER_S`` past the birth. So the true ceiling is the larger of
# those two, and this is stated as their sum instead — a strictly looser
# bound, chosen because it stays a valid ceiling if either mechanism is
# retuned, and because summing them is the arithmetic a reader will do anyway.
# ``tests/test_night_ghost.py`` asserts it across seeds and source counts.
MAX_VOICE_TOTAL_S = MAX_VOICE_S * OUTLIVE_MAX + HANDOVER_COVER_S


@dataclass(frozen=True)
class Voice:
    """One thing that is born, sounds for a few minutes, and dies.

    A voice now names *what it is made of*: a synthesized texture drawn from
    the seed, or a loop belonging to a prepared source (``texture ==
    "source"``). ``gain`` is the pair balance and applies to every voice,
    not only halves of a pair — a solitary synth voice simply carries
    ``1.0``. ``source_id`` set on a non-``"source"`` texture means *this is
    the ghost of that source*, which is exactly what ``is_ghost`` reads;
    ``loop_index`` only means anything when ``texture == "source"``.
    """

    index: int
    birth_frame: int
    n_frames: int
    pitch_hz: float
    texture: str
    decay: StemDecayConfig
    source_id: str | None = None
    loop_index: int = 0
    gain: float = 1.0

    @property
    def key(self) -> str:
        """The RNG key naming this voice. Composed here and nowhere else.

        Same discipline as ``disintegration.decayed_iteration``: one place
        builds the string, so two code paths cannot derive different noise for
        the same voice.
        """
        return f"night:voice:{self.index}"


def is_ghost(voice: Voice) -> bool:
    """True for a voice synthesized from a source's own spectrum.

    A ghost is not a separate generator — it is a drone or a noise band whose
    pitch came from a ``SourceProfile`` rather than from the seed. What makes
    it a ghost is the provenance, which is why this is a function rather than
    a texture.
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


def _birth_gap_s(density: float, rng) -> float:
    """Seconds until the next birth, stretched as the night thins out.

    The rng parameter is not annotated (it would require a numpy import this
    module is forbidden to make).
    """
    stretch = 1.0 + (1.0 - density) * (_SPARSEST_STRETCH - 1.0)
    return float(rng.uniform(_BIRTH_GAP_MIN_S, _BIRTH_GAP_MAX_S)) * stretch


def interval_set(moon_phase: float) -> tuple[int, ...]:
    """The intervals a voice may sit at under this moon.

    The spec's steering table gives moon phase exactly one job — "width of the
    interval set", full → more open, new → nearer unison — and this is it.
    Openness is ``1 - 2 * |phase - 0.5|``: 1.0 at full moon, 0.0 at new, and
    monotone in the distance from full in both directions, so a waxing and a
    waning quarter are the same night. That openness picks how many of
    ``_INTERVALS_CENTS`` are reachable, from ``_MIN_INTERVAL_WIDTH`` at new to
    all of them at full — so a full moon can reach the octave and the fifth
    above it, and a new moon cannot.

    **Why this lives here and not in ``clock.py``.** The rule at the top of
    ``clock.py`` is that steering enters the *arc* in one place, and the arc is
    four descending ceilings. Interval width is not a ceiling: it is not a
    thing that descends, and there is no arc field it could be. So it enters
    at the one place downstream of the arc that already owns pitch, with the
    same discipline the arc's own mappings keep — one input, one parameter,
    monotone, bounded. It emphatically does not enter ``palette.py``, which
    would be a second home for steering rather than a further step of one.

    Bounded by construction, which is what makes "no combination is unsafe"
    checkable rather than empirical: the result is always a non-empty prefix
    of a tuple every member of which is consonant, so no phase — including a
    nonsense one — can produce an empty set or a dissonant interval.
    """
    phase = min(max(float(moon_phase), 0.0), 1.0)
    openness = 1.0 - 2.0 * abs(phase - 0.5)
    span = len(_INTERVALS_CENTS) - _MIN_INTERVAL_WIDTH
    width = _MIN_INTERVAL_WIDTH + int(round(openness * span))
    return _INTERVALS_CENTS[:width]


def _pitch_hz(root_hz: float, cents: float) -> float:
    return root_hz * (2.0 ** (cents / 1200.0))


def _decay_for(arc: NightArc, base: StemDecayConfig) -> StemDecayConfig:
    """A decay config whose endpoints *are* this moment's ceilings.

    Rendered at ``progress = 1.0``, so the start values never apply and are
    left at the dataclass defaults rather than being invented here — with one
    exception. The noise floor is set at *both* ends, to the same value, so
    that it cannot matter which progress a future caller renders at: the hiss
    a voice carries is the same wherever in its own arc it is asked for, and
    it descends with the night because it is pinned to ``arc.level_db`` rather
    than to a number in the dataclass. See ``NOISE_BELOW_LEVEL_DB``.
    """
    hiss_db = arc.level_db + NOISE_BELOW_LEVEL_DB
    return replace(base,
                   enabled=True,
                   lowpass_end_hz=arc.brightness_hz,
                   amp_end_db=arc.level_db,
                   noise_start_db=hiss_db,
                   noise_end_db=hiss_db)


def plan_voices(ctx: NightContext, sr: int, from_frame: int,
                to_frame: int) -> list[Voice]:
    """Every voice sounding at any point in ``[from_frame, to_frame)``.

    A voice counts as sounding if it is born before the window ends and dies
    after the window begins. Its reverb tail may extend past its death; that is
    the renderer's business, not the plan's, and padding the plan for it would
    make ``Voice.n_frames`` mean two things.

    **With sources in play, every step consumes exactly two voice indices**,
    ``index`` for the primary voice and ``index + 1`` for its ghost, whether
    or not either is actually emitted — and both share the one RNG keyed on
    ``index``. That is what keeps a window's answer identical to the whole
    night's answer restricted to it: nothing about how many voices a step
    *emits* is allowed to change how far the walk has *advanced*. Every draw
    a step might need — lifetime, interval slot, texture, loop pick,
    ghost-pitch pick, the outlive roll, the gap — happens unconditionally,
    before any branch on ``stage``, for the same reason: a draw made inside
    an ``if`` would make the RNG stream depend on which branch fired, and the
    symptom is a night that is reproducible until the sources folder changes
    and then silently is not.

    **With no sources at all, both the stride and the draw shape fall back
    to exactly Phase 1's.** ``Voice.key`` — and so every voice's own
    material and decay noise — is derived from ``index`` alone, so an
    unconditional stride of two would still change every voice's identity
    even on a night with nothing to pair. That is only half of it, though:
    Phase 1 drew four things a step (lifetime, interval slot, texture, the
    birth gap); a pairing step draws eight (those four, plus the loop pick,
    the ghost-pitch pick, the outlive roll and the outlive factor). Drawing
    the extra four unconditionally, even with no sources to spend them on,
    still shifts *where in the generator's own state* the birth-gap draw
    lands relative to Phase 1 — so the gap value differs, the cursor walks
    to a different place, and every voice after the first diverges from
    what an empty ``ctx.sources`` is supposed to reproduce *exactly*.

    So both decisions — the stride, and whether to draw the pair-only four
    — are made once, from ``has_sources``, before the walk starts. Neither
    weakens the "every draw happens on every step" rule above: that rule
    exists so a decision cannot depend on something two different windows
    might resolve differently, and ``ctx.sources`` is fixed for the whole
    night and identical in every window of it. A per-context constant is
    not a per-step branch.
    """
    if to_frame <= from_frame:
        return []

    root_rng = iteration_rng(ctx.seed, "night:root", 0)
    root_hz = float(root_rng.choice(_ROOT_CHOICES_HZ))
    night_frames = max(int(ctx.night_length_s * sr), 1)
    intervals = interval_set(ctx.moon_phase)
    schedule = schedule_sources(ctx, sr, night_frames)
    has_sources = bool(ctx.sources)
    stride = 2 if has_sources else 1

    # Every genuine handover of the night, ascending, computed once.
    #
    # **A stage boundary is a seam only when the source actually changes
    # across it.** ``schedule_sources`` emits a boundary every time a stage
    # ends, including when the source on both sides is the same one — a
    # single-source night still walks through several stages, all pointing at
    # index 0. A boundary from a source back to itself is not a handover: the
    # material does not change across it, so the ordinary birth gap already
    # carries it, the same as any other stretch of one source's own night.
    # Counting every boundary as a seam regardless fired the cover on
    # stretches with nothing to cover — measured at 17.9% of walk steps on a
    # one-source night, source voices stretched past 800 s by it, and the
    # ghost's own ``OUTLIVE_CHANCE`` flourish suppressed (via ``not seams``
    # below) for most of the night even though nothing needed covering.
    #
    # Hoisted out of the walk because it is pure arithmetic on ``schedule``,
    # which is fixed for the night: recomputing it per step bought nothing,
    # and the clamp below has to look *ahead* of the cursor rather than only
    # inside one step's gap.
    seam_frames = tuple(
        schedule[i].end_frame for i in range(len(schedule) - 1)
        if schedule[i].source_index != schedule[i + 1].source_index)
    approach = max(int(SEAM_APPROACH_S * sr), 1)

    voices: list[Voice] = []
    base_decay = StemDecayConfig()
    index = 0
    cursor = 0

    while cursor < to_frame:
        rng = iteration_rng(ctx.seed, "night:voice", index)
        t_s = cursor / sr
        arc = arc_at(t_s, ctx)
        elapsed = min(max(cursor / night_frames, 0.0), 1.0)

        # -- every draw, unconditionally, before any branch --------------
        lifetime_s = float(rng.uniform(MIN_VOICE_S, MAX_VOICE_S))
        # Drawn over the *fixed* width of ``_INTERVALS_CENTS``, never over
        # ``intervals`` itself — see the comment this one echoes below,
        # where the reasoning was first written down. A draw whose width
        # tracked the moon's narrowing would consume a different amount of
        # this step's generator state depending on the phase, which would
        # shift every draw after it, including the birth gap, and the moon
        # would be steering the schedule as well as the pitch.
        slot = int(rng.choice(len(_INTERVALS_CENTS)))
        synth_texture = str(rng.choice(TEXTURES[:2]))
        # These four exist only to serve a pair, and are drawn only when
        # ``has_sources`` — a per-context constant, not a per-step branch,
        # for the same reason ``stride`` is one. Drawing them unconditionally
        # would still be "every draw happens on every step" in letter, but it
        # would shift where the birth-gap draw lands in the generator's own
        # state on a night with nothing to pair them with, which is exactly
        # the class of drift rule 2 exists to prevent — it would silently
        # move Phase 1's own schedule, not just its voices' keys.
        if has_sources:
            loop_pick = int(rng.integers(0, 1024))
            pitch_pick = int(rng.integers(0, 1024))
            outlive_roll = float(rng.random())
            outlive_factor = float(rng.uniform(OUTLIVE_MIN, OUTLIVE_MAX))
        gap_s = _birth_gap_s(arc.density, rng)

        # The root falls as the night goes; the interval sits on top of it.
        cents = intervals[slot % len(intervals)]
        descent = -ROOT_DESCENT_SEMITONES * elapsed * 100.0
        n_frames = int(lifetime_s * sr)
        decay = _decay_for(arc, base_decay)
        next_cursor = cursor + max(int(gap_s * sr), 1)

        # -- do not let this step jump a seam from an arbitrary distance --
        #
        # Whatever this step emits is the last chance to cover any seam its
        # gap crosses, and the cover reaches from ``cursor``, so an unclamped
        # gap makes the covering voice as long as the gap is. Instead: if a
        # genuine seam falls inside this gap and is further than ``approach``
        # away, stop the step short at ``seam - approach``. This step then
        # crosses no seam at all, and the *next* step — born ``approach``
        # before it, well inside the smallest gap any density can draw — is
        # the one that covers it, from a distance this constant bounds.
        #
        # The loop leaves the invariant every seam still admitted is within
        # ``approach`` of ``cursor``, so ``reach`` below cannot exceed
        # ``SEAM_APPROACH_S + HANDOVER_COVER_S``. It also terminates and
        # always advances: the clamp only fires when ``seam - cursor >
        # approach``, so ``seam - approach`` is strictly past ``cursor``.
        #
        # A seam is never skipped by the clamp. ``cursor`` can only land on
        # or past a seam via a step whose ``next_cursor`` was at least that
        # seam — and any such step had the seam in its own ``seams``, so it
        # covered it before moving on.
        for seam in seam_frames:
            if seam <= cursor:
                continue
            if seam > next_cursor:
                break
            if seam - cursor > approach:
                next_cursor = seam - approach
                break

        stage = stage_at(schedule, cursor)
        emitted: list[Voice] = []

        # Every genuine handover this step's gap crosses. Whatever this step
        # emits must reach past the *furthest* one, not just its own stage's
        # end — a gap that crosses several still leaves every one covered,
        # because the covering voice's interval is contiguous from ``cursor``
        # onward and so passes through all of them on the way to the
        # furthest. (With ``STAGE_MIN_S`` at 20 minutes against an
        # ``approach`` of seconds, the clamp above means only one seam can be
        # in range at a time in practice; the ``max`` costs nothing and keeps
        # the code correct if either constant moves.)
        seams = [s for s in seam_frames if cursor < s <= next_cursor]

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

            if ratio > MIN_AUDIBLE_RATIO and profile.loop_paths:
                emitted.append(Voice(
                    index=index, birth_frame=cursor, n_frames=n_frames,
                    pitch_hz=0.0, texture="source", decay=decay,
                    source_id=profile.source_id,
                    loop_index=loop_pick % len(profile.loop_paths),
                    gain=source_gain))

            if profile.pitch_set and (1.0 - ratio) > MIN_AUDIBLE_RATIO:
                ghost_frames = n_frames
                if not seams and outlive_roll < OUTLIVE_CHANCE:
                    # Occasionally, away from a handover: a flourish, not
                    # the rule.
                    ghost_frames = int(ghost_frames * outlive_factor)
                # The artistic cap applies only to the ghost's natural or
                # occasionally-outliving lifetime, never to the handover
                # cover below — see the cover step after this branch for
                # why the cap cannot be allowed to reach that far.
                #
                # It no longer binds: ``OUTLIVE_MAX`` is 2.5, so the line
                # above cannot produce more than ``MAX_VOICE_S * 2.5``
                # anyway. Kept because the two constants are independent and
                # nothing else stops a future ``OUTLIVE_MAX`` of 4 from
                # putting a sixteen-minute ghost into a night.
                ghost_frames = min(ghost_frames, int(MAX_VOICE_S * sr * 3))

                base_hz = profile.pitch_set[pitch_pick % len(profile.pitch_set)]
                emitted.append(Voice(
                    index=index + 1, birth_frame=cursor,
                    n_frames=ghost_frames,
                    pitch_hz=_pitch_hz(base_hz, descent),
                    texture=synth_texture, decay=decay,
                    source_id=profile.source_id, gain=ghost_gain))

            if not emitted:
                # A pitchless source at the far end of the night, or one
                # too quiet to be worth either half, has neither half
                # left. Fall back rather than emitting silence.
                emitted.append(Voice(
                    index=index, birth_frame=cursor, n_frames=n_frames,
                    pitch_hz=_pitch_hz(root_hz, cents + descent),
                    texture=synth_texture, decay=decay))

        if seams and emitted:
            # Systematically at a handover: whatever is still sounding
            # across the seam is what hides it — a ghost, an in-progress
            # source loop, or (a pitchless source is ordinary, not
            # exceptional — see ``pitch.py``) the synthesis fallback. The
            # cover is not a property of any one texture, so it does not
            # assume a ghost exists: it stretches whichever *emitted* voice
            # is already longest-lived, the same gesture the design already
            # sanctions for a ghost outliving its source. Done last, after
            # every cap above, so nothing tunable can shrink it back down —
            # the systematic cover at a handover is not tunable to nothing
            # without reintroducing the event it exists to hide.
            #
            # ``reach`` is bounded because the walk was clamped, not because
            # anything clamps it here: the seam-approach step above
            # guarantees ``max(seams) - cursor <= approach``, so this is at
            # most ``SEAM_APPROACH_S + HANDOVER_COVER_S``. See
            # ``SEAM_APPROACH_S`` for what it used to cost when it was not.
            reach = max(seams) - cursor + int(HANDOVER_COVER_S * sr)
            longest = max(range(len(emitted)), key=lambda i: emitted[i].n_frames)
            if emitted[longest].n_frames < reach:
                emitted[longest] = replace(emitted[longest], n_frames=reach)

        for voice in emitted:
            if voice.birth_frame < to_frame and (
                    voice.birth_frame + voice.n_frames > from_frame):
                voices.append(voice)

        cursor = next_cursor
        index += stride  # a pair's worth with sources; one voice without

    # A pair shares a birth frame; ``index`` breaks the tie so a source
    # voice always precedes its own ghost, which is also the order the walk
    # already appends them in — this sort is a safety net, not a fix.
    voices.sort(key=lambda v: (v.birth_frame, v.index))
    return voices


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

    The next source is chosen as the nearest in pitch **among those that have
    not yet played this round**, so the overlap during a handover is consonant
    and a night with six songs in it visits six songs. Excluding only the
    immediately-previous source is not enough: that makes the successor a pure
    function of the current source, which settles into a two-cycle within a
    stage or two and turns six prepared songs into a night of two. See the
    selection rule in the body for the measurement. With one source the rule
    is inert; with none there is no schedule at all.

    **A ``Stage`` boundary is not itself a handover.** With one source every
    stage still names the same ``source_index``, because the selection rule
    above never runs — so a one-source night still produces several stages,
    all pointing at index 0, purely from the stage-length draw. Whether a
    boundary is a genuine handover — the thing worth covering — is decided
    by whoever reads the schedule, by comparing ``source_index`` on either
    side of it; see ``plan_voices``' own ``seams`` for where that comparison
    is made and why it has to be.
    """
    if not ctx.sources:
        return ()

    stages: list[Stage] = []
    cursor = 0
    step = 0
    current = int(iteration_rng(ctx.seed, "night:stage", 0)
                  .integers(0, len(ctx.sources)))
    # Who has already held the stage this round. See the selection rule
    # below for why "this round" and not "ever".
    played = {current}

    while cursor < night_frames:
        rng = iteration_rng(ctx.seed, "night:stage", step + 1)
        # A stage must advance the cursor by at least one frame. Without the
        # floor, a degenerate sample rate (0, or small enough that the
        # product truncates to 0) would draw a zero-length stage forever and
        # this loop would never reach ``night_frames`` — the same failure
        # mode ``plan_voices``' birth-gap draw already guards against with
        # the same ``max(..., 1)``.
        length = max(int(float(rng.uniform(STAGE_MIN_S, STAGE_MAX_S)) * sr), 1)
        stages.append(Stage(source_index=current, start_frame=cursor,
                            end_frame=cursor + length))
        cursor += length
        step += 1

        if len(ctx.sources) > 1:
            # **Nearest among those not yet played this round**, not simply
            # nearest. The pure-nearest rule was locally correct — the next
            # source genuinely *was* the closest available — and composed
            # into something the spec does not want: with only the
            # immediately-previous source excluded, the successor map is a
            # pure function of ``current`` with no other input, so it walks
            # into a cycle and stays there. Measured over eight seeds with
            # six well-separated sources, every night visited **two or three
            # distinct sources across ~15 stages** — six prepared songs
            # yielding a night of two. The spec's own scenario is "an
            # eight-hour night with six sources taking turns", and a
            # 2-cycle is not taking turns.
            #
            # Tracking who has played turns the map into a function of
            # ``(current, played)``, which cannot cycle before the round is
            # out: every source is visited exactly once per round, and the
            # round then restarts from wherever it ended. The nearest-in-
            # pitch preference is untouched — it now orders the remaining
            # candidates rather than all of them, so each handover is still
            # the most consonant one *available*.
            #
            # Deterministic and RNG-free, exactly as before: ``played`` is a
            # function of the stage index alone, so a schedule is still
            # reproducible from the seed and identical in every window of the
            # night.
            candidates = [i for i in range(len(ctx.sources)) if i not in played]
            if not candidates:
                # The round is out. Start a new one. The ``i != current``
                # filter just below is what refuses to hand a source
                # straight back to itself here — with exactly two sources
                # this reset path runs at every boundary, so that filter is
                # the entire no-repeat mechanism, and the pair simply
                # alternates as before. ``played = {current}`` is a
                # different, weaker thing: it keeps the source that just
                # finished out of the *new* round's rotation too, rather
                # than letting it come back as soon as one other source has
                # played. That is a rotation nicety, not a repeat guard —
                # nothing currently exercises it (``played = set()`` here
                # passes the full suite unchanged), so a future test that
                # wants to pin it starts here.
                played = {current}
                candidates = [i for i in range(len(ctx.sources))
                              if i != current]
            # ``, i`` breaks a pitch-distance tie by lowest index, so the
            # pick never depends on the traversal order ``min`` happens to
            # see ties in. ``candidates`` is a plain list built by ascending
            # index, so that order is already deterministic here — but
            # relying on that incidentally would make this line correct only
            # by accident of how ``candidates`` happens to be built today.
            #
            # Convention: nearest *from* the outgoing source's own voice —
            # ``pitch_distance(current, candidate)``, not the reverse.
            # ``pitch_distance`` is not symmetric, and a reviewer built a
            # concrete counterexample where the two orders pick different
            # winners, so this is a stated default pending an ear test, not
            # a formality.
            current = min(candidates, key=lambda i: (
                pitch_distance(ctx.sources[current], ctx.sources[i]), i))
            played.add(current)

    return tuple(stages)


def stage_at(schedule: tuple[Stage, ...], frame: int) -> Stage | None:
    """The stage covering ``frame``, or ``None``.

    Past the end clamps to the last stage rather than falling off, so a stream
    that outlives its own arc keeps its material instead of going synthetic.
    A frame before the night, or an empty schedule, has no stage at all.
    """
    if not schedule or frame < 0:
        return None
    for stage in schedule:
        if stage.start_frame <= frame < stage.end_frame:
            return stage
    return schedule[-1] if frame >= schedule[-1].end_frame else None
