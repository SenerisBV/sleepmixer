"""The planner, exercised over a whole night in a unit test.

It touches no audio at all, which is the entire reason an eight-hour night can
be asserted here in microseconds rather than rendered. If an import of
``sleepmix.audio`` ever appears in ``night/plan.py``, this file stops being
able to do its job.
"""
from pathlib import Path

from sleepmix.night.clock import arc_at
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    MAX_VOICE_S, MIN_VOICE_S, TEXTURES, Voice, plan_voices,
)

from .import_guard import imports_any

SR = 44100


def _context(seed: int = 1, length_s: float = 8 * 3600.0) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=length_s,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)


def _whole_night(ctx: NightContext) -> list[Voice]:
    return plan_voices(ctx, SR, 0, int(ctx.night_length_s * SR))


def test_plan_module_imports_no_audio():
    """Verify plan.py has no audio or heavy deps — using AST to catch all spellings."""
    import sleepmix.night.plan as plan_module
    plan_path = Path(plan_module.__file__)

    # Top-level modules that must never be imported
    forbidden_toplevel = {"numpy", "scipy", "soundfile", "pedalboard"}

    # Module paths that must never be imported (catches both absolute and relative)
    forbidden_from = {
        "sleepmix.audio",
        "sleepmix.effects",
        "sleepmix.disintegration",
        "sleepmix.soundbed",
        "sleepmix.palette",
    }

    assert not imports_any(
        str(plan_path),
        forbidden_toplevel,
        forbidden_from
    ), (
        f"Module {plan_path.name} imports a forbidden module. "
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
