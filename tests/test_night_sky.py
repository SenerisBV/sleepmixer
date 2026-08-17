"""The sky, checked against published almanac values.

Tolerances are minutes, not seconds: this is the standard low-precision
sunrise equation (no refraction model beyond the fixed -0.833 degree
correction, no topography), which is the right precision for deciding how
long a night is and the wrong precision for navigation.
"""
import datetime as dt

import pytest

from sleepmix.night.sky import day_length_h, moon_phase, solar_events

AMSTERDAM = (52.3676, 4.9041)


def _minutes_apart(a: dt.datetime, b: dt.datetime) -> float:
    return abs((a - b).total_seconds()) / 60.0


def test_midwinter_sunrise_over_amsterdam():
    rise, _ = solar_events(dt.date(2026, 12, 21), *AMSTERDAM)
    expected = dt.datetime(2026, 12, 21, 7, 47, tzinfo=dt.timezone.utc)
    assert _minutes_apart(rise, expected) < 6.0


def test_midsummer_sunrise_over_amsterdam():
    rise, _ = solar_events(dt.date(2026, 6, 21), *AMSTERDAM)
    expected = dt.datetime(2026, 6, 21, 3, 18, tzinfo=dt.timezone.utc)
    assert _minutes_apart(rise, expected) < 6.0


def test_sunset_follows_sunrise():
    rise, set_ = solar_events(dt.date(2026, 3, 15), *AMSTERDAM)
    assert set_ > rise


def test_the_december_day_is_far_shorter_than_the_june_one():
    december = day_length_h(dt.date(2026, 12, 21), *AMSTERDAM)
    june = day_length_h(dt.date(2026, 6, 21), *AMSTERDAM)
    assert december < 8.5
    assert june > 16.0
    # The whole point of reading the night's length from the sky: at this
    # latitude the two differ by most of a working day.
    assert june - december > 8.0


@pytest.mark.parametrize("when,expected", [
    (dt.datetime(2026, 1, 18, 19, 52, tzinfo=dt.timezone.utc), 0.0),   # new moon
    (dt.datetime(2026, 2, 1, 22, 9, tzinfo=dt.timezone.utc), 0.5),     # full moon
])
def test_moon_phase_at_known_syzygies(when, expected):
    phase = moon_phase(when)
    # Phase wraps, so 0.99 is as close to 0.0 as 0.01 is.
    distance = min(abs(phase - expected), 1.0 - abs(phase - expected))
    assert distance < 0.04


def test_moon_phase_always_in_range():
    start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    for day in range(0, 400, 7):
        phase = moon_phase(start + dt.timedelta(days=day))
        assert 0.0 <= phase < 1.0
