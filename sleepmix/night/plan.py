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
        stage = stage_at(schedule, cursor)
        emitted: list[Voice] = []

        # Every genuine handover this step's gap would cross without a later
        # voice being born before it: whatever this step emits is the last
        # chance to cover it, so it must reach past the *furthest* one, not
        # just its own stage's end. A gap sparse enough to skip several
        # handovers still leaves every one of them covered, because the
        # covering voice's interval is contiguous from ``cursor`` onward
        # and so passes through all of them on the way to the furthest.
        # Computed unconditionally — it is pure arithmetic on ``schedule``,
        # not a draw, so computing it here costs nothing on a night with no
        # sources, where it is always empty (``schedule`` is empty too).
        #
        # **A stage boundary is a seam only when the source actually
        # changes across it.** ``schedule_sources`` emits a boundary every
        # time a stage ends, including when the source on both sides is the
        # same one — a single-source night still walks through several
        # stages, all pointing at index 0. A boundary from a source back to
        # itself is not a handover: the material does not change across it,
        # so the ordinary birth gap already carries it, the same as any
        # other stretch of one source's own night. Counting every boundary
        # as a seam regardless fired the cover on stretches with nothing to
        # cover — measured at 17.9% of walk steps on a one-source night,
        # source voices stretched past 800 s by it, and the ghost's own
        # ``OUTLIVE_CHANCE`` flourish suppressed (via ``not seams`` below)
        # for most of the night even though nothing needed covering.
        seams = [schedule[i].end_frame for i in range(len(schedule) - 1)
                if cursor < schedule[i].end_frame <= next_cursor
                and schedule[i].source_index != schedule[i + 1].source_index]

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

    The next source is chosen as the nearest in pitch among those not just
    used, so the overlap during a handover is consonant. With one source the
    rule is inert; with none there is no schedule at all.

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
            candidates = [i for i in range(len(ctx.sources)) if i != current]
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
