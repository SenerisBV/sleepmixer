"""Sunrise, sunset and moon phase from coordinates alone.

No network, no service, no API key — this is arithmetic, and it is the
cheapest steering input in the design by a wide margin. At Dutch latitude a
December night and a June night are about nine hours of darkness apart, which
is the difference this module exists to let the arc read.

The algorithm is the standard low-precision sunrise equation. It is accurate
to a few minutes, which is the right precision for deciding how long a night
is and the wrong precision for anything else.
"""
from __future__ import annotations

import datetime as dt
import math

# Days per synodic month, and a known new moon to count from.
_SYNODIC_MONTH_DAYS = 29.530588853
_KNOWN_NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)

# Sun's angular radius plus atmospheric refraction at the horizon.
_HORIZON_DEG = -0.833
_OBLIQUITY_DEG = 23.4397


def _julian_day(date: dt.date) -> float:
    """Julian day number for 12:00 UTC on ``date``."""
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    jdn = (date.day + (153 * m + 2) // 5 + 365 * y + y // 4
           - y // 100 + y // 400 - 32045)
    return float(jdn)


def _from_julian(j: float) -> dt.datetime:
    """Inverse of ``_julian_day``, keeping the fractional part as a time."""
    unix_seconds = (j - 2440587.5) * 86400.0
    return dt.datetime.fromtimestamp(unix_seconds, tz=dt.timezone.utc)


def solar_events(date: dt.date, lat_deg: float,
                 lon_deg: float) -> tuple[dt.datetime, dt.datetime]:
    """Return ``(sunrise_utc, sunset_utc)`` for ``date`` at these coordinates.

    Above the polar circles the sun may never cross the horizon, in which case
    ``acos`` has no solution. Rather than raise — a program that refuses to
    start a night because the operator is in Tromsø is worse than one that
    guesses — the hour angle is clamped, which degrades to the solar transit
    for polar night, and to the surrounding midnights for the midnight sun.
    The clamp is why this returns values everywhere.
    """
    n = _julian_day(date) - 2451545.0 + 0.0008
    j_star = n - lon_deg / 360.0

    mean_anomaly = math.radians((357.5291 + 0.98560028 * j_star) % 360.0)
    center = (1.9148 * math.sin(mean_anomaly)
              + 0.0200 * math.sin(2 * mean_anomaly)
              + 0.0003 * math.sin(3 * mean_anomaly))
    ecliptic_lon = math.radians(
        (math.degrees(mean_anomaly) + center + 180.0 + 102.9372) % 360.0)

    j_transit = (2451545.0 + j_star
                 + 0.0053 * math.sin(mean_anomaly)
                 - 0.0069 * math.sin(2 * ecliptic_lon))

    declination = math.asin(
        math.sin(ecliptic_lon) * math.sin(math.radians(_OBLIQUITY_DEG)))

    phi = math.radians(lat_deg)
    numerator = (math.sin(math.radians(_HORIZON_DEG))
                 - math.sin(phi) * math.sin(declination))
    denominator = math.cos(phi) * math.cos(declination)
    cos_hour_angle = numerator / denominator if denominator != 0 else 0.0
    cos_hour_angle = max(-1.0, min(1.0, cos_hour_angle))
    hour_angle = math.degrees(math.acos(cos_hour_angle))

    return (_from_julian(j_transit - hour_angle / 360.0),
            _from_julian(j_transit + hour_angle / 360.0))


def day_length_h(date: dt.date, lat_deg: float, lon_deg: float) -> float:
    """Hours of daylight on ``date``. Feeds the season half of the steering."""
    rise, set_ = solar_events(date, lat_deg, lon_deg)
    return (set_ - rise).total_seconds() / 3600.0


def moon_phase(when: dt.datetime) -> float:
    """Fraction through the synodic month: 0.0 new, 0.5 full, wrapping.

    Naive datetimes are read as UTC rather than rejected — every caller in this
    package builds its own aware datetimes, so a naive one arriving here is a
    test or a REPL, and neither is worth an exception.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    elapsed_days = (when - _KNOWN_NEW_MOON).total_seconds() / 86400.0
    return (elapsed_days % _SYNODIC_MONTH_DAYS) / _SYNODIC_MONTH_DAYS
