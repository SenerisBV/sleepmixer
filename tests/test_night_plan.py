"""The planner, exercised over a whole night in a unit test.

It touches no audio at all, which is the entire reason an eight-hour night can
be asserted here in microseconds rather than rendered. If an import of
``sleepmix.audio`` ever appears in ``night/plan.py``, this file stops being
able to do its job.
"""
import math
from pathlib import Path

from sleepmix.night.clock import arc_at
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    MAX_VOICE_S, MIN_VOICE_S, TEXTURES, Voice, _INTERVALS_CENTS,
    _MIN_INTERVAL_WIDTH, interval_set, plan_voices,
)

from .import_guard import forbidden_imports

SR = 44100


def _context(seed: int = 1, length_s: float = 8 * 3600.0,
             moon: float = 0.5) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=length_s,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=moon, day_length_h=12.0)


def _whole_night(ctx: NightContext) -> list[Voice]:
    return plan_voices(ctx, SR, 0, int(ctx.night_length_s * SR))


def test_plan_module_imports_no_audio():
    """Verify plan.py has no audio or heavy deps — using AST to catch all spellings."""
    import sleepmix.night.plan as plan_module
    plan_path = Path(plan_module.__file__)
    repo_root = Path(plan_module.__file__).parent.parent.parent  # sleepmix/night/plan.py -> root

    forbidden = {
        "numpy", "scipy", "soundfile", "pedalboard",
        "sleepmix.audio",
        "sleepmix.effects",
        "sleepmix.disintegration",
        "sleepmix.soundbed",
        "sleepmix.night.palette",
        "sleepmix.night.stream",
        "sleepmix.night.pitch",
        "sleepmix.night.prepare",
    }

    violations = forbidden_imports(plan_path, repo_root, forbidden)
    assert not violations, (
        f"Module plan.py imports forbidden modules: {violations}. "
        "The planner must have no audio or heavy dependencies to enable "
        "eight-hour nights to be tested in microseconds."
    )


def test_a_night_produces_voices():
    voices = _whole_night(_context())
    assert len(voices) > 20


def test_the_plan_is_reproducible_from_seed_alone():
    assert _whole_night(_context(seed=42)) == _whole_night(_context(seed=42))


def test_a_different_seed_gives_a_different_night():
    assert _whole_night(_context(seed=1)) != _whole_night(_context(seed=2))


def test_a_window_matches_the_whole_night_restricted_to_it():
    """The property the block renderer depends on.

    Asking for the voices alive in one ten-second window must give exactly
    what a full-night plan, filtered to that window, gives — otherwise a block
    rendered on its own is not the same block.
    """
    ctx = _context()
    start, end = 3000 * SR, 3010 * SR
    windowed = plan_voices(ctx, SR, start, end)
    expected = [v for v in _whole_night(ctx)
                if v.birth_frame < end and v.birth_frame + v.n_frames > start]
    assert windowed == expected


def test_voices_are_born_in_order():
    voices = _whole_night(_context())
    births = [v.birth_frame for v in voices]
    assert births == sorted(births)


def test_voice_indices_are_unique_and_stable():
    voices = _whole_night(_context())
    indices = [v.index for v in voices]
    assert len(indices) == len(set(indices))
    assert all(v.key == f"night:voice:{v.index}" for v in voices)


def test_lifetimes_stay_inside_their_bounds():
    for voice in _whole_night(_context()):
        seconds = voice.n_frames / SR
        assert MIN_VOICE_S <= seconds <= MAX_VOICE_S


def test_every_texture_is_one_this_palette_can_render():
    assert {v.texture for v in _whole_night(_context())} <= set(TEXTURES)


def test_a_voice_is_never_born_above_the_ceiling_at_its_birth():
    """The nested-clocks rule, asserted.

    A voice born at hour six may not start bright. Its decay endpoints are
    exactly the arc's ceilings at the moment it was born.
    """
    ctx = _context()
    for voice in _whole_night(ctx):
        arc = arc_at(voice.birth_frame / SR, ctx)
        assert voice.decay.lowpass_end_hz <= arc.brightness_hz + 1e-6
        assert voice.decay.amp_end_db <= arc.level_db + 1e-9


def test_the_night_thins_out_as_it_goes():
    """Density is the arc's, not the planner's, but it must actually land."""
    ctx = _context()
    voices = _whole_night(ctx)
    half = int(ctx.night_length_s * SR / 2)
    first_half = [v for v in voices if v.birth_frame < half]
    second_half = [v for v in voices if v.birth_frame >= half]
    assert len(second_half) < len(first_half) / 2


def test_the_root_descends_across_the_night():
    ctx = _context()
    voices = _whole_night(ctx)
    early = [v.pitch_hz for v in voices[:5]]
    late = [v.pitch_hz for v in voices[-5:]]
    # Voices sit at different intervals above the root, so compare the floors.
    assert min(late) < min(early)


def test_an_empty_window_is_an_empty_list():
    ctx = _context()
    assert plan_voices(ctx, SR, 10 * SR, 10 * SR) == []


def test_planning_a_whole_night_is_fast():
    import time
    ctx = _context()
    began = time.perf_counter()
    _whole_night(ctx)
    assert time.perf_counter() - began < 0.5


# -- the moon ---------------------------------------------------------------
#
# The spec's steering table gives moon phase one job: "width of the interval
# set", full -> more open, new -> nearer unison. It was computed in ``sky.py``,
# carried into ``NightContext``, and then read by nobody — one of the two
# steering rows that did nothing when the branch was first handed over.


def _cents_above_root(ctx: NightContext) -> set[int]:
    """Every interval a night's voices actually land on, in cents.

    Recovered from the pitches rather than trusted from the constant: the
    root descends across the night, so each pitch is divided by the root at
    its own birth before the interval is read back out.
    """
    from sleepmix.night.plan import (
        ROOT_DESCENT_SEMITONES, _ROOT_CHOICES_HZ, _pitch_hz,
    )
    from sleepmix.util import iteration_rng

    root = float(iteration_rng(ctx.seed, "night:root", 0).choice(
        _ROOT_CHOICES_HZ))
    night_frames = max(int(ctx.night_length_s * SR), 1)

    found = set()
    for voice in _whole_night(ctx):
        elapsed = min(max(voice.birth_frame / night_frames, 0.0), 1.0)
        descent = -ROOT_DESCENT_SEMITONES * elapsed * 100.0
        here = _pitch_hz(root, descent)
        found.add(int(round(1200.0 * math.log2(voice.pitch_hz / here))))
    return found


def test_a_full_moon_opens_the_interval_set_wider_than_a_new_moon():
    """Everything else equal — same seed, same weather, same night."""
    full = _cents_above_root(_context(moon=0.5))
    new = _cents_above_root(_context(moon=0.0))
    assert new < full, f"new moon {sorted(new)} vs full {sorted(full)}"
    # And the widening is specifically at the top: the open intervals.
    assert 1200 in full and 1900 in full
    assert 1200 not in new and 1900 not in new


def test_the_moon_widens_the_set_monotonically_from_new_to_full():
    widths = [len(interval_set(p / 40.0)) for p in range(21)]  # 0.0 -> 0.5
    assert widths == sorted(widths)
    assert widths[0] == _MIN_INTERVAL_WIDTH
    assert widths[-1] == len(_INTERVALS_CENTS)


def test_the_moons_effect_is_bounded_over_the_whole_phase_range():
    """The steering discipline, asserted the way ``test_night_clock``'s sweep
    asserts it for the arc: no phase, including a nonsense one, may produce a
    set that is empty, that is not consonant, or that is wider than the tuple
    it is drawn from."""
    phases = [p / 200.0 for p in range(201)]
    phases += [-3.0, -0.001, 1.001, 7.5, float("inf")]
    for phase in phases:
        intervals = interval_set(phase)
        assert _MIN_INTERVAL_WIDTH <= len(intervals) <= len(_INTERVALS_CENTS)
        assert set(intervals) <= set(_INTERVALS_CENTS)
        # Waxing and waning are the same night: only the distance from full
        # matters, so a phase and its mirror give the same set.
        if 0.0 <= phase <= 1.0:
            assert interval_set(1.0 - phase) == intervals


def test_no_moon_moves_a_single_birth():
    """One input, one parameter.

    The interval is drawn from the same generator ``_birth_gap_s`` uses, so a
    draw whose width varied with the phase would move every birth time in the
    night — and the moon would be steering the schedule as well as the pitch.
    """
    reference = [(v.index, v.birth_frame, v.n_frames, v.texture)
                 for v in _whole_night(_context(moon=0.5))]
    for phase in (0.0, 0.17, 0.25, 0.5, 0.75, 0.93, 1.0):
        night = [(v.index, v.birth_frame, v.n_frames, v.texture)
                 for v in _whole_night(_context(moon=phase))]
        assert night == reference, f"moon {phase} moved the night's schedule"


def test_the_plan_is_reproducible_from_seed_and_context_together():
    for phase in (0.0, 0.3, 0.5, 0.87):
        a = _whole_night(_context(seed=42, moon=phase))
        b = _whole_night(_context(seed=42, moon=phase))
        assert a == b
