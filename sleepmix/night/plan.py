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

from dataclasses import dataclass, replace

from ..config import StemDecayConfig
from ..util import iteration_rng
from .clock import arc_at, NightArc
from .context import NightContext
from .sources import pitch_distance

TEXTURES = ("drone", "noiseband")

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


@dataclass(frozen=True)
class Voice:
    """One thing that is born, sounds for a few minutes, and dies."""

    index: int
    birth_frame: int
    n_frames: int
    pitch_hz: float
    texture: str
    decay: StemDecayConfig

    @property
    def key(self) -> str:
        """The RNG key naming this voice. Composed here and nowhere else.

        Same discipline as ``disintegration.decayed_iteration``: one place
        builds the string, so two code paths cannot derive different noise for
        the same voice.
        """
        return f"night:voice:{self.index}"


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
    """
    if to_frame <= from_frame:
        return []

    root_rng = iteration_rng(ctx.seed, "night:root", 0)
    root_hz = float(root_rng.choice(_ROOT_CHOICES_HZ))
    night_frames = max(int(ctx.night_length_s * sr), 1)
    intervals = interval_set(ctx.moon_phase)

    voices: list[Voice] = []
    base_decay = StemDecayConfig()
    index = 0
    cursor = 0

    while cursor < to_frame:
        rng = iteration_rng(ctx.seed, "night:voice", index)
        t_s = cursor / sr
        arc = arc_at(t_s, ctx)

        lifetime_s = float(rng.uniform(MIN_VOICE_S, MAX_VOICE_S))
        n_frames = int(lifetime_s * sr)

        # The root falls as the night goes; the interval sits on top of it.
        elapsed = min(max(cursor / night_frames, 0.0), 1.0)
        descent = -ROOT_DESCENT_SEMITONES * elapsed * 100.0
        # The draw is over the *whole* tuple's length whatever the moon is
        # doing, and the moon only decides what that draw lands on. That is
        # not a stylistic preference: this generator is shared with
        # ``_birth_gap_s`` below, so a draw whose width varied with the phase
        # would move every birth time in the night and the moon would be
        # steering the schedule as well as the pitch. Drawing a fixed-width
        # slot and folding it into the reachable set leaves the RNG stream
        # identical for every phase — and, at full moon, leaves the whole
        # expression identical to what it was before the moon reached it.
        slot = int(rng.choice(len(_INTERVALS_CENTS)))
        cents = intervals[slot % len(intervals)]
        pitch = _pitch_hz(root_hz, cents + descent)

        voice = Voice(
            index=index,
            birth_frame=cursor,
            n_frames=n_frames,
            pitch_hz=pitch,
            texture=str(rng.choice(TEXTURES)),
            decay=_decay_for(arc, base_decay),
        )
        if voice.birth_frame < to_frame and (
                voice.birth_frame + voice.n_frames > from_frame):
            voices.append(voice)

        cursor += max(int(_birth_gap_s(arc.density, rng) * sr), 1)
        index += 1

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
