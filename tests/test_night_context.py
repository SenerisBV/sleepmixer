"""The dusk snapshot, and the thing it must never do: fail to be taken.

Every function here is on the path between pressing one button and hearing
sound. A weather service that is down, slow, or returning nonsense must cost
the operator nothing at all.
"""
import datetime as dt

import pytest

from sleepmix.night import context as ctx_mod
from sleepmix.night.context import (
    MAX_NIGHT_S, MIN_NIGHT_S, NEUTRAL_WEATHER, Weather, build_context,
    fetch_weather, night_length_s,
)

AMSTERDAM = (52.3676, 4.9041)


def test_an_ordinary_winter_night_is_used_as_measured():
    assert night_length_s(8.5 * 3600.0) == pytest.approx(8.5 * 3600.0)


def test_a_short_summer_night_is_floored():
    # Going to bed at 03:00 in June: sunrise is two hours off, and compressing
    # the whole descent into two hours would be a different piece of music.
    assert night_length_s(2.0 * 3600.0) == MIN_NIGHT_S


def test_an_arctic_winter_night_is_capped():
    assert night_length_s(20.0 * 3600.0) == MAX_NIGHT_S


def test_a_sunrise_already_past_is_floored_rather_than_negative():
    assert night_length_s(-1800.0) == MIN_NIGHT_S


def test_fetch_weather_returns_neutral_when_the_service_raises(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("no network at 3am")

    monkeypatch.setattr(ctx_mod, "_get_json", explode)
    assert fetch_weather(*AMSTERDAM) == NEUTRAL_WEATHER


def test_fetch_weather_returns_neutral_when_the_payload_is_nonsense(monkeypatch):
    monkeypatch.setattr(ctx_mod, "_get_json", lambda *a, **k: {"unexpected": True})
    assert fetch_weather(*AMSTERDAM) == NEUTRAL_WEATHER


def test_fetch_weather_reads_a_well_formed_payload(monkeypatch):
    payload = {
        "current": {
            "cloud_cover": 75,
            "precipitation": 1.2,
            "wind_speed_10m": 6.5,
            "pressure_msl": 998.0,
        },
        "hourly": {"pressure_msl": [1004.0, 1002.0, 1000.0, 998.0]},
    }
    monkeypatch.setattr(ctx_mod, "_get_json", lambda *a, **k: payload)
    weather = fetch_weather(*AMSTERDAM)
    assert weather.cloud_cover == pytest.approx(0.75)
    assert weather.precipitation_mm == pytest.approx(1.2)
    assert weather.wind_ms == pytest.approx(6.5)
    assert weather.pressure_hpa == pytest.approx(998.0)
    # Falling pressure reads as a negative trend.
    assert weather.pressure_trend_hpa == pytest.approx(-6.0)


def test_cloud_cover_is_clamped_even_if_the_service_lies(monkeypatch):
    payload = {"current": {"cloud_cover": 480, "precipitation": -3.0,
                           "wind_speed_10m": 4.0, "pressure_msl": 1013.0},
               "hourly": {"pressure_msl": []}}
    monkeypatch.setattr(ctx_mod, "_get_json", lambda *a, **k: payload)
    weather = fetch_weather(*AMSTERDAM)
    assert weather.cloud_cover == 1.0
    assert weather.precipitation_mm == 0.0


def test_build_context_survives_a_dead_weather_service(monkeypatch):
    monkeypatch.setattr(ctx_mod, "_get_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    when = dt.datetime(2026, 12, 21, 22, 30, tzinfo=dt.timezone.utc)
    context = build_context(when, *AMSTERDAM, seed=7)
    assert context.weather == NEUTRAL_WEATHER
    assert MIN_NIGHT_S <= context.night_length_s <= MAX_NIGHT_S
    assert context.seed == 7


def test_build_context_is_reproducible(monkeypatch):
    monkeypatch.setattr(ctx_mod, "_get_json", lambda *a, **k: {})
    when = dt.datetime(2026, 3, 3, 23, 0, tzinfo=dt.timezone.utc)
    assert build_context(when, *AMSTERDAM, seed=1) == build_context(
        when, *AMSTERDAM, seed=1)


def test_a_december_night_is_longer_than_a_june_one(monkeypatch):
    monkeypatch.setattr(ctx_mod, "_get_json", lambda *a, **k: {})
    december = build_context(
        dt.datetime(2026, 12, 21, 22, 30, tzinfo=dt.timezone.utc),
        *AMSTERDAM, seed=1)
    june = build_context(
        dt.datetime(2026, 6, 21, 22, 30, tzinfo=dt.timezone.utc),
        *AMSTERDAM, seed=1)
    assert december.night_length_s > june.night_length_s
    assert december.day_length_h < june.day_length_h


def test_weather_is_frozen():
    with pytest.raises(Exception):
        NEUTRAL_WEATHER.wind_ms = 99.0  # type: ignore[misc]
