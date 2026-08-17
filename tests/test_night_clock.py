"""The arc: the one thing in this program that may only ever go down.

Two properties are load-bearing and both are asserted by sweeping rather than
by spot checks. Monotonicity is what makes "quieter and sparser as the night
goes on" structural instead of decorative. Boundedness across the whole
steering space is what stops the weather from being able to produce a bad
night — steering varies character, never quality.
"""
import itertools

import pytest

from sleepmix.night.clock import NightArc, arc_at
from sleepmix.night.context import (
    MAX_NIGHT_S, MIN_NIGHT_S, NightContext, Weather,
)


def _context(**weather_overrides) -> NightContext:
    base = dict(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                pressure_hpa=1013.25, pressure_trend_hpa=0.0)
    base.update(weather_overrides)
    return NightContext(seed=1, night_length_s=8 * 3600.0,
                        weather=Weather(**base), moon_phase=0.5,
                        day_length_h=12.0)


def _sweep(ctx: NightContext, steps: int = 200):
    return [arc_at(ctx.night_length_s * i / steps, ctx)
            for i in range(steps + 1)]


def test_every_quantity_is_monotone_non_increasing():
    for previous, current in itertools.pairwise(_sweep(_context())):
        assert current.density <= previous.density + 1e-9
        assert current.brightness_hz <= previous.brightness_hz + 1e-6
        assert current.level_db <= previous.level_db + 1e-9
        assert current.intelligibility <= previous.intelligibility + 1e-9


def test_the_night_ends_quiet_dark_and_sparse():
    ctx = _context()
    start, end = arc_at(0.0, ctx), arc_at(ctx.night_length_s, ctx)
    assert end.level_db < start.level_db - 10.0
    assert end.brightness_hz < start.brightness_hz / 4.0
    assert end.density < 0.2
    assert end.intelligibility < 0.1


def test_speech_is_never_clear_even_at_the_start():
    # Intelligible speech at any hour is the failure mode of the project. The
    # ceiling starts below 1.0 on purpose.
    assert arc_at(0.0, _context()).intelligibility < 0.85


def test_time_past_the_end_clamps_rather_than_overshooting():
    ctx = _context()
    at_end = arc_at(ctx.night_length_s, ctx)
    way_past = arc_at(ctx.night_length_s * 5, ctx)
    assert way_past == at_end


def test_negative_time_clamps_to_the_start():
    ctx = _context()
    assert arc_at(-500.0, ctx) == arc_at(0.0, ctx)


def test_a_wet_night_is_no_brighter_than_a_dry_one():
    dry = arc_at(0.0, _context(cloud_cover=0.0, precipitation_mm=0.0))
    wet = arc_at(0.0, _context(cloud_cover=1.0, precipitation_mm=12.0))
    assert wet.brightness_hz <= dry.brightness_hz


def test_falling_pressure_darkens():
    steady = arc_at(0.0, _context(pressure_trend_hpa=0.0))
    falling = arc_at(0.0, _context(pressure_trend_hpa=-12.0))
    assert falling.brightness_hz < steady.brightness_hz


def test_the_whole_steering_space_stays_inside_the_ceilings():
    """Steering varies character, never quality.

    No combination of weather, moon and season may produce a night that is
    brighter, louder, denser or more intelligible than the design's ceilings.
    """
    clouds = [0.0, 0.5, 1.0]
    precipitation = [0.0, 20.0]
    winds = [0.0, 25.0]
    trends = [-20.0, 0.0, 20.0]
    moons = [0.0, 0.5, 0.99]
    lengths = [MIN_NIGHT_S, MAX_NIGHT_S]

    for cloud, rain, wind, trend, moon, length in itertools.product(
            clouds, precipitation, winds, trends, moons, lengths):
        ctx = NightContext(
            seed=1, night_length_s=length,
            weather=Weather(cloud_cover=cloud, precipitation_mm=rain,
                            wind_ms=wind, pressure_hpa=1013.25,
                            pressure_trend_hpa=trend),
            moon_phase=moon, day_length_h=8.0)
        for arc in _sweep(ctx, steps=40):
            assert 0.0 <= arc.density <= 1.0
            assert 100.0 <= arc.brightness_hz <= 6000.0
            assert -60.0 <= arc.level_db <= 0.0
            assert 0.0 <= arc.intelligibility <= 0.85


def test_the_arc_is_frozen():
    with pytest.raises(Exception):
        arc_at(0.0, _context()).density = 1.0  # type: ignore[misc]
