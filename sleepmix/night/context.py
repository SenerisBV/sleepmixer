"""One immutable snapshot of the world, taken when the button is pressed.

Everything the night is steered by is fetched or computed here, once, and then
held constant until morning. That is deliberate: a stream that re-read the
weather at 3 AM could change character while someone was asleep in it, and
"the weather turned" is exactly the kind of event this program exists not to
produce.

The other rule this module lives by is that **nothing here may prevent a night
from starting**. ``fetch_weather`` and ``build_context`` catch everything and
fall back to neutral values. A sleep tool that refuses to make a sound because
a forecast API is down has failed at the only job it has.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .sky import day_length_h, moon_phase, solar_events

# The clamp on how long a night may be. Both bounds are placeholders in the
# sense docs/project-state.md means it: invented, not measured, and due for
# revision by someone who has actually slept through this. The floor exists so
# that starting at 03:00 in June does not compress the whole descent into
# ninety minutes; the ceiling so that an arctic winter does not stretch it into
# something that never audibly moves.
MIN_NIGHT_S = 6 * 3600.0
MAX_NIGHT_S = 10 * 3600.0

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class Weather:
    """The four scalars the steering table reads, and nothing else."""

    cloud_cover: float          # 0..1
    precipitation_mm: float     # >= 0
    wind_ms: float              # >= 0
    pressure_hpa: float
    pressure_trend_hpa: float   # negative = falling


# What an unremarkable night looks like. Used whenever the service is
# unreachable, slow, or returning something this module does not recognise.
NEUTRAL_WEATHER = Weather(
    cloud_cover=0.5,
    precipitation_mm=0.0,
    wind_ms=3.0,
    pressure_hpa=1013.25,
    pressure_trend_hpa=0.0,
)


@dataclass(frozen=True)
class NightContext:
    """Everything the planner and the arc are allowed to read."""

    seed: int
    night_length_s: float
    weather: Weather
    moon_phase: float
    day_length_h: float


def night_length_s(seconds_until_sunrise: float) -> float:
    """Clamp the measured darkness remaining into a usable night."""
    return float(min(max(seconds_until_sunrise, MIN_NIGHT_S), MAX_NIGHT_S))


def _get_json(url: str, params: dict, timeout_s: float) -> dict:
    """One HTTP GET returning parsed JSON.

    Factored out so tests can replace the network without patching a library
    they do not otherwise care about, and imported inside the function per this
    project's graceful-degradation policy — ``import sleepmix`` must not need
    ``requests`` installed.
    """
    import requests

    response = requests.get(url, params=params, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def fetch_weather(lat_deg: float, lon_deg: float,
                  timeout_s: float = 5.0) -> Weather:
    """Today's weather at these coordinates, or ``NEUTRAL_WEATHER``.

    Open-Meteo needs no key and no attribution, which is why it is the one
    chosen: there is nothing to manage for a personal tool. Every failure —
    network, HTTP status, malformed JSON, a field that moved — lands in the
    same place, because from this function's point of view they are the same
    event: no usable weather, start the night anyway.
    """
    try:
        payload = _get_json(_OPEN_METEO_URL, {
            "latitude": lat_deg,
            "longitude": lon_deg,
            "current": "cloud_cover,precipitation,wind_speed_10m,pressure_msl",
            "hourly": "pressure_msl",
            "past_hours": 3,
            "forecast_hours": 1,
        }, timeout_s)

        current = payload["current"]
        cloud = min(max(float(current["cloud_cover"]) / 100.0, 0.0), 1.0)
        precipitation = max(float(current["precipitation"]), 0.0)
        wind = max(float(current["wind_speed_10m"]), 0.0)
        pressure = float(current["pressure_msl"])

        series = [float(p) for p in payload["hourly"]["pressure_msl"]
                  if p is not None]
        trend = (series[-1] - series[0]) if len(series) >= 2 else 0.0

        return Weather(cloud_cover=cloud, precipitation_mm=precipitation,
                       wind_ms=wind, pressure_hpa=pressure,
                       pressure_trend_hpa=trend)
    except Exception:
        return NEUTRAL_WEATHER


def build_context(now: dt.datetime, lat_deg: float, lon_deg: float,
                  seed: int) -> NightContext:
    """Take the snapshot. Never raises.

    ``now`` is expected to be timezone-aware UTC. The sunrise looked for is
    tomorrow's if today's has already happened, which is the ordinary case at
    the hour anybody presses this button.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)

    try:
        rise, _ = solar_events(now.date(), lat_deg, lon_deg)
        if rise <= now:
            rise, _ = solar_events(now.date() + dt.timedelta(days=1),
                                   lat_deg, lon_deg)
        until_sunrise = (rise - now).total_seconds()
        length = night_length_s(until_sunrise)
        daylight = day_length_h(now.date(), lat_deg, lon_deg)
        phase = moon_phase(now)
    except Exception:
        length, daylight, phase = MIN_NIGHT_S, 12.0, 0.5

    return NightContext(
        seed=seed,
        night_length_s=length,
        weather=fetch_weather(lat_deg, lon_deg),
        moon_phase=phase,
        day_length_h=daylight,
    )
