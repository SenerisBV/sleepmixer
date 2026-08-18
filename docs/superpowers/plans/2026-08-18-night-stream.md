# The Night Stream (Plan 5, Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sleepmix night` plays an indefinite, evolving, self-quieting ambient stream with live voices floating over it, all night, with no configuration.

**Architecture:** A pure planner decides which synthesized voices are born when, under ceilings that descend across the night; a block renderer produces ten-second blocks of that deterministic music ahead of playback; a player mixes a live speech layer in at the output, where non-determinism is allowed to live. The existing decay, reverb and sound-bed code is reused unchanged — only the material feeding it is new.

**Tech Stack:** Python 3.10+, numpy, scipy, `sounddevice` (new), `requests` (new, for one weather call and one audio stream), click. No Demucs, no librosa, no torch anywhere in this plan.

**Spec:** `docs/superpowers/specs/2026-08-18-night-stream-design.md`

## Global Constraints

- **`night/` may import from `sleepmix/`, never the reverse.** No existing module gains an import of `sleepmix.night`.
- **`night/plan.py`, `night/clock.py`, `night/context.py` and `night/sky.py` may not import anything that generates or decodes audio.** They may import `sleepmix.config` (dataclasses only) and `sleepmix.util`. This is what makes an eight-hour night assertable in microseconds.
- **Block independence:** block *N* of the music layer rendered in isolation is bit-identical to blocks 0..*N* rendered in sequence. Nothing live may enter `night/stream.py`.
- **No transients.** Every voice fades in and out over seconds. No generator may produce an attack.
- **Degrade silently.** Every error path in the runtime ends in *less sound*, never in different sound and never in no stream. Nothing prints to stdout during a night.
- **Heavy or optional dependencies are imported inside the function that needs them**, never at module scope, with a working fallback — the existing policy in `docs/architecture.md` under "Graceful degradation".
- **New optional dependency group:** `night = ["sounddevice>=0.4", "requests>=2.31"]`.
- Tests live in `tests/` alongside the existing suite and run under `pipenv run pytest -q`.

## Deviation from the spec, flagged for review

The spec names **KiwiSDR** as the Phase 1 radio source. This plan ships the squelch gate, the over-the-air treatment and the `SpeechSource` interface in Phase 1, but drives them from an **HTTP/Icecast audio stream** rather than a KiwiSDR websocket.

The reason is task honesty, not preference. The KiwiSDR wire protocol (websocket `SET` commands plus IMA-ADPCM audio decoding) cannot be written out as exact code in a plan without first reading the `jks-prv/kiwiclient` source, and a task containing approximate protocol code is worse than a task that does not claim to. Everything that creates the *aesthetic* — the gate, the band-limiting, the level drift, the intelligibility ceiling — is transport-independent and ships here in full. A `KiwiSource` implementing the same `SpeechSource` interface is then a small, well-bounded follow-up rather than an unspecifiable hole in the middle of a large task.

If this is not acceptable, the fix is to insert a spike before Task 8 and re-plan that one task; nothing else in the plan moves.

## File structure

| File | Responsibility |
|---|---|
| `sleepmix/night/__init__.py` | Package marker. Exports nothing. |
| `sleepmix/night/sky.py` | Pure astronomy: sunrise/sunset from coordinates, moon phase, day length. No network. |
| `sleepmix/night/context.py` | `Weather`, `NightContext`, the Open-Meteo client, the neutral fallback, and the night-length clamp. Imports `sky`. |
| `sleepmix/night/clock.py` | `NightArc` and `arc_at(t, ctx)` — the four descending ceilings. Imports `context`. |
| `sleepmix/night/plan.py` | `Voice` and `plan_voices(...)` — the unbounded planner. Imports `clock`. No audio. |
| `sleepmix/night/palette.py` | The two generators plus the no-transient fade. Produces raw `AudioBuffer`s. |
| `sleepmix/night/stream.py` | `NightStream`: the voice cache, per-voice decay and reverb, block assembly, the noise bed. The deterministic layer, entire. |
| `sleepmix/night/speech.py` | `SpeechSource`, `RoomSource`, `RadioSource`, `SilentSource`, the squelch gate, the two distance treatments. |
| `sleepmix/night/player.py` | Block queue, `sounddevice` output, the live speech mix, the player-generated fallback bed, degradation. |
| `sleepmix/cli.py` | Gains the `night` command. |
| `tests/test_night_sky.py` … `tests/test_night_player.py` | One test module per source module. |

---

### Task 1: The sky — sunrise, moon, and day length

**Files:**
- Create: `sleepmix/night/__init__.py`
- Create: `sleepmix/night/sky.py`
- Test: `tests/test_night_sky.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `solar_events(date: datetime.date, lat_deg: float, lon_deg: float) -> tuple[datetime, datetime]` — `(sunrise_utc, sunset_utc)`, both timezone-aware UTC.
  - `day_length_h(date: datetime.date, lat_deg: float, lon_deg: float) -> float`
  - `moon_phase(when: datetime) -> float` — 0.0 new, 0.5 full, wrapping in [0, 1).

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_sky.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_sky.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night'`

- [ ] **Step 3: Create the package marker**

Create `sleepmix/night/__init__.py`:

```python
"""The night stream: an indefinite, self-quieting ambient stream.

This package may import from ``sleepmix``; nothing in ``sleepmix`` may import
from here. See ``docs/superpowers/specs/2026-08-18-night-stream-design.md``.
"""
```

- [ ] **Step 4: Write the implementation**

Create `sleepmix/night/sky.py`:

```python
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
    guesses — the hour angle is clamped, which degrades to a nominal midnight
    sunrise and midday sunset. The clamp is why this returns values everywhere.
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_sky.py -q`
Expected: PASS, 7 passed

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/__init__.py sleepmix/night/sky.py tests/test_night_sky.py
git commit -m "feat: the night reads sunrise and moon out of arithmetic"
```

---

### Task 2: The context — one immutable snapshot taken at dusk

**Files:**
- Create: `sleepmix/night/context.py`
- Test: `tests/test_night_context.py`
- Modify: `pyproject.toml` (add the `night` optional-dependency group)

**Interfaces:**
- Consumes: `sleepmix.night.sky.solar_events`, `day_length_h`, `moon_phase`.
- Produces:
  - `MIN_NIGHT_S = 6 * 3600.0`, `MAX_NIGHT_S = 10 * 3600.0`
  - `Weather` frozen dataclass: `cloud_cover: float` (0–1), `precipitation_mm: float`, `wind_ms: float`, `pressure_hpa: float`, `pressure_trend_hpa: float`
  - `NEUTRAL_WEATHER: Weather`
  - `fetch_weather(lat_deg: float, lon_deg: float, timeout_s: float = 5.0) -> Weather` — never raises
  - `night_length_s(seconds_until_sunrise: float) -> float`
  - `NightContext` frozen dataclass: `seed: int`, `night_length_s: float`, `weather: Weather`, `moon_phase: float`, `day_length_h: float`
  - `build_context(now: datetime, lat_deg: float, lon_deg: float, seed: int) -> NightContext` — never raises

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_context.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_context.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.context'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/context.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_context.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Add the optional-dependency group**

In `pyproject.toml`, under `[project.optional-dependencies]`, add after the `ui` line:

```toml
night = ["sounddevice>=0.4", "requests>=2.31"]
```

and add the same two entries to the `all` list, so `pip install "sleepmix[all]"` can run a night:

```toml
all = ["demucs>=4.0", "torch>=2.0", "librosa>=0.10", "pyrubberband>=0.3", "soxr>=0.3",
       "fastapi>=0.110", "uvicorn>=0.27", "sounddevice>=0.4", "requests>=2.31"]
```

- [ ] **Step 6: Verify the whole suite still passes**

Run: `pipenv run pytest -q`
Expected: PASS, no regressions against the 348-test baseline

- [ ] **Step 7: Commit**

```bash
git add sleepmix/night/context.py tests/test_night_context.py pyproject.toml
git commit -m "feat: the dusk snapshot, which nothing is allowed to prevent"
```

---

### Task 3: The arc — four ceilings that only ever descend

**Files:**
- Create: `sleepmix/night/clock.py`
- Test: `tests/test_night_clock.py`

**Interfaces:**
- Consumes: `sleepmix.night.context.NightContext`, `Weather`; `sleepmix.util.shape_progress`, `lerp`.
- Produces:
  - `NightArc` frozen dataclass: `density: float` (0–1), `brightness_hz: float`, `level_db: float`, `intelligibility: float` (0–1)
  - `arc_at(t_s: float, ctx: NightContext) -> NightArc`
  - `ARC_CURVE = "log"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_clock.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_clock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.clock'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/clock.py`:

```python
"""The night arc: four ceilings that descend, and nothing that raises them.

This is the outer of the two nested clocks in the design. It never resets and
it is never a suggestion — a voice born at hour six is *built* under whatever
these values are at hour six, so nothing can inject fresh energy at 4 AM. That
is why the arc is a constraint on what may exist rather than an automation
curve laid over the top: there is no louder thing for it to be fighting.

Steering enters here and only here, and the discipline is one input, one
parameter, monotone, bounded. Every mapping below is a small multiplier on a
starting value, and the sweep in ``tests/test_night_clock.py`` is what enforces
that no combination of them can escape the design's ceilings.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..util import lerp, shape_progress
from .context import NightContext

# Ease-out: the stream gets quiet and dark fairly quickly, then lingers there
# for the rest of the night. The alternative — holding bright and collapsing
# late — puts the sharpest change at the hour it is least wanted.
ARC_CURVE = "log"

# The arc's endpoints. All four are first drafts and all four want tuning by
# ear; see the placeholder note in the spec.
_DENSITY_START, _DENSITY_END = 1.0, 0.05
_BRIGHTNESS_START_HZ, _BRIGHTNESS_END_HZ = 6000.0, 500.0
_LEVEL_START_DB, _LEVEL_END_DB = 0.0, -18.0
_INTELLIGIBILITY_START, _INTELLIGIBILITY_END = 0.80, 0.03

# Hard floors and ceilings the steering may never push past. These are what
# make "the whole steering space is safe" a checkable property.
_MIN_BRIGHTNESS_HZ, _MAX_BRIGHTNESS_HZ = 100.0, 6000.0
_MIN_LEVEL_DB, _MAX_LEVEL_DB = -60.0, 0.0


@dataclass(frozen=True)
class NightArc:
    """What the night permits at one moment.

    ``density`` is a 0..1 abstraction the planner turns into voice spacing;
    ``brightness_hz`` and ``level_db`` become a voice's decay endpoints
    directly; ``intelligibility`` is read by the player, not the renderer,
    because the speech layer is mixed live.
    """

    density: float
    brightness_hz: float
    level_db: float
    intelligibility: float


def _brightness_multiplier(ctx: NightContext) -> float:
    """Cloud, rain, pressure trend and season, each pulling one way only.

    Every term is at most 1.0, so the product is at most 1.0: steering can
    darken a night and can never brighten one past the arc's own start. That
    one-sidedness is what makes the sweep test provable rather than empirical.
    """
    weather = ctx.weather
    cloud = 1.0 - 0.20 * weather.cloud_cover
    rain = 1.0 - 0.15 * min(weather.precipitation_mm / 10.0, 1.0)
    # Falling pressure darkens; rising pressure is merely neutral.
    falling = min(max(-weather.pressure_trend_hpa / 15.0, 0.0), 1.0)
    pressure = 1.0 - 0.15 * falling
    # Deeper winter (shorter days) is darker as well as longer.
    winter = min(max((12.0 - ctx.day_length_h) / 8.0, 0.0), 1.0)
    season = 1.0 - 0.15 * winter
    return cloud * rain * pressure * season


def arc_at(t_s: float, ctx: NightContext) -> NightArc:
    """The four ceilings ``t_s`` seconds into the night.

    Time outside the night clamps to its ends rather than extrapolating: a
    stream that outlives its own arc should hold at its quietest, not descend
    through the floor into negative brightness.
    """
    length = max(ctx.night_length_s, 1.0)
    progress = shape_progress(min(max(t_s / length, 0.0), 1.0), ARC_CURVE)

    brightness = lerp(_BRIGHTNESS_START_HZ, _BRIGHTNESS_END_HZ, progress)
    brightness *= _brightness_multiplier(ctx)

    return NightArc(
        density=lerp(_DENSITY_START, _DENSITY_END, progress),
        brightness_hz=min(max(brightness, _MIN_BRIGHTNESS_HZ),
                          _MAX_BRIGHTNESS_HZ),
        level_db=min(max(lerp(_LEVEL_START_DB, _LEVEL_END_DB, progress),
                         _MIN_LEVEL_DB), _MAX_LEVEL_DB),
        intelligibility=lerp(_INTELLIGIBILITY_START, _INTELLIGIBILITY_END,
                             progress),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_clock.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add sleepmix/night/clock.py tests/test_night_clock.py
git commit -m "feat: the arc, which may only ever go down"
```

---

### Task 4: The planner — an eight-hour night in microseconds

**Files:**
- Create: `sleepmix/night/plan.py`
- Test: `tests/test_night_plan.py`

**Interfaces:**
- Consumes: `sleepmix.night.clock.arc_at`, `NightArc`; `sleepmix.night.context.NightContext`; `sleepmix.config.StemDecayConfig`; `sleepmix.util.iteration_rng`.
- Produces:
  - `Voice` frozen dataclass: `index: int`, `birth_frame: int`, `n_frames: int`, `pitch_hz: float`, `texture: str`, `decay: StemDecayConfig`; property `key -> str` returning `f"night:voice:{index}"`
  - `plan_voices(ctx: NightContext, sr: int, from_frame: int, to_frame: int) -> list[Voice]`
  - `TEXTURES = ("drone", "noiseband")`
  - `MIN_VOICE_S = 45.0`, `MAX_VOICE_S = 240.0`
  - `ROOT_DESCENT_SEMITONES = 1.0`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_plan.py`:

```python
"""The planner, exercised over a whole night in a unit test.

It touches no audio at all, which is the entire reason an eight-hour night can
be asserted here in microseconds rather than rendered. If an import of
``sleepmix.audio`` ever appears in ``night/plan.py``, this file stops being
able to do its job.
"""
import pytest

from sleepmix.night.clock import arc_at
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import (
    MAX_VOICE_S, MIN_VOICE_S, TEXTURES, Voice, plan_voices,
)

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
    import sleepmix.night.plan as plan_module
    source = open(plan_module.__file__).read()
    assert "sleepmix.audio" not in source
    assert "import numpy" not in source


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_plan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.plan'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/plan.py`:

```python
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
from .clock import arc_at
from .context import NightContext

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
_INTERVALS_CENTS = (0, 200, 500, 700, 1200, 1900)

# How far the root falls across a whole night. Imperceptible minute to minute,
# unmistakable between 23:00 and 05:00, and the same gesture the decay engine
# already makes in the frequency domain.
ROOT_DESCENT_SEMITONES = 1.0


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
    """Seconds until the next birth, stretched as the night thins out."""
    stretch = 1.0 + (1.0 - density) * (_SPARSEST_STRETCH - 1.0)
    return float(rng.uniform(_BIRTH_GAP_MIN_S, _BIRTH_GAP_MAX_S)) * stretch


def _pitch_hz(root_hz: float, cents: int) -> float:
    return root_hz * (2.0 ** (cents / 1200.0))


def _decay_for(arc, base: StemDecayConfig) -> StemDecayConfig:
    """A decay config whose endpoints *are* this moment's ceilings.

    Rendered at ``progress = 1.0``, so the start values never apply and are
    left at the dataclass defaults rather than being invented here.
    """
    return replace(base,
                   enabled=True,
                   lowpass_end_hz=arc.brightness_hz,
                   amp_end_db=arc.level_db)


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
        cents = int(rng.choice(_INTERVALS_CENTS))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_plan.py -q`
Expected: PASS, 14 passed

- [ ] **Step 5: Commit**

```bash
git add sleepmix/night/plan.py tests/test_night_plan.py
git commit -m "feat: a plan for who is born when, and under what ceiling"
```

---

### Task 5: The palette — two generators, neither of which may start

**Files:**
- Create: `sleepmix/night/palette.py`
- Test: `tests/test_night_palette.py`

**Interfaces:**
- Consumes: `sleepmix.night.plan.Voice`; `sleepmix.audio.AudioBuffer`; `sleepmix.util.iteration_rng`.
- Produces:
  - `render_voice(voice: Voice, sr: int, seed: int) -> AudioBuffer` — stereo, `voice.n_frames` long, faded at both ends
  - `FADE_S = 6.0`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_palette.py`:

```python
"""The generators, and the one rule they may not break.

No transients. Every voice must arrive and leave over seconds, because an
attack is an event and events wake people up. That is asserted directly here
rather than left to listening, since it is the property most likely to be
broken by an innocent-looking change to either generator.
"""
import numpy as np
import pytest

from sleepmix.config import StemDecayConfig
from sleepmix.night.palette import FADE_S, render_voice
from sleepmix.night.plan import Voice

SR = 22050


def _voice(texture: str = "drone", index: int = 0, seconds: float = 60.0,
           pitch_hz: float = 110.0) -> Voice:
    return Voice(index=index, birth_frame=0, n_frames=int(seconds * SR),
                 pitch_hz=pitch_hz, texture=texture, decay=StemDecayConfig())


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_stereo_and_the_length_it_says_it_is(texture):
    voice = _voice(texture)
    buf = render_voice(voice, SR, seed=1)
    assert buf.n_frames == voice.n_frames
    assert buf.n_channels == 2
    assert buf.sr == SR


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_attack(texture):
    """The first moments must be far quieter than the middle."""
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    opening = x[:int(0.05 * SR)].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert opening < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_release_cliff(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    closing = x[-int(0.05 * SR):].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert closing < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_reproducible(texture):
    a = render_voice(_voice(texture), SR, seed=5)
    b = render_voice(_voice(texture), SR, seed=5)
    assert np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_different_voices_draw_different_noise(texture):
    a = render_voice(_voice(texture, index=0), SR, seed=5)
    b = render_voice(_voice(texture, index=1), SR, seed=5)
    assert not np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_nothing_clips(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    assert np.abs(buf.data).max() <= 1.0


def test_a_drone_sits_at_the_pitch_it_was_asked_for():
    voice = _voice("drone", pitch_hz=110.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    # Look at the sustained middle, away from the fades.
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 110.0) < 3.0


def test_a_noiseband_is_centred_near_its_pitch_and_is_not_a_tone():
    voice = _voice("noiseband", pitch_hz=220.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 220.0) < 60.0
    # A tone puts nearly all its energy in one bin; a band does not.
    assert spectrum.max() / spectrum.sum() < 0.05


def test_a_voice_shorter_than_two_fades_still_fades_both_ends():
    voice = _voice("drone", seconds=FADE_S)
    buf = render_voice(voice, SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    assert x[0] < 1e-4
    assert x[-1] < 1e-4
    assert x.max() > 1e-3


def test_an_unknown_texture_is_refused():
    with pytest.raises(ValueError, match="unknown texture"):
        render_voice(_voice("trumpet"), SR, seed=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_palette.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.palette'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/palette.py`:

```python
"""Two generators, and the fade that keeps either from being an event.

Neither of these is trying to sound like a synthesiser. They are trying to
sound like something that was recorded and has since eroded, because that is
the family this program belongs to — and because everything they produce is
about to be handed to ``apply_decay``, which was written for tape and behaves
best on material with some noise and some drift already in it.

The hard rule is **no transients**. Every voice fades in and out over
``FADE_S`` seconds, and the fade is applied here rather than by the caller so
that no future caller can forget it.
"""
from __future__ import annotations

import numpy as np

from ..audio import AudioBuffer
from ..util import iteration_rng
from .plan import Voice

# Long enough that arrival and departure are never noticed as moments. This is
# a taste value and a first draft.
FADE_S = 6.0

# Partials in a drone, as multiples of the fundamental, with the amplitude each
# gets. Weighted down steeply: the point is a fundamental with a halo, not an
# organ stop.
_PARTIALS = ((1.0, 1.00), (2.0, 0.32), (3.0, 0.14), (4.0, 0.07), (6.0, 0.04))

# How far each partial is allowed to drift in pitch and level, and how slowly.
_DETUNE_CENTS = 7.0
_DRIFT_DEPTH = 0.35
_DRIFT_MIN_HZ, _DRIFT_MAX_HZ = 0.013, 0.11

_PEAK = 0.35  # leaves headroom for several concurrent voices to sum


def _fade_envelope(n: int, sr: int) -> np.ndarray:
    """A raised-cosine fade at both ends, halved if the voice is too short."""
    fade = min(int(FADE_S * sr), n // 2)
    env = np.ones(n, dtype=np.float32)
    if fade > 0:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade,
                                              dtype=np.float32))
        env[:fade] = ramp
        env[-fade:] = ramp[::-1]
    return env


def _slow_drift(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """A gentle 0..1 amplitude wobble, slow enough to read as breathing."""
    rate = float(rng.uniform(_DRIFT_MIN_HZ, _DRIFT_MAX_HZ))
    phase = float(rng.uniform(0.0, 2 * np.pi))
    t = np.arange(n, dtype=np.float32) / sr
    return (1.0 - _DRIFT_DEPTH
            + _DRIFT_DEPTH * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t + phase)))


def _drone(n: int, sr: int, pitch_hz: float,
           rng: np.random.Generator) -> np.ndarray:
    """Additive partials, each detuned and drifting on its own clock."""
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    for multiple, amplitude in _PARTIALS:
        cents = float(rng.uniform(-_DETUNE_CENTS, _DETUNE_CENTS))
        freq = pitch_hz * multiple * (2.0 ** (cents / 1200.0))
        if freq >= sr / 2:
            continue
        phase = float(rng.uniform(0.0, 2 * np.pi))
        tone = np.sin(2 * np.pi * freq * t + phase, dtype=np.float32)
        out += tone * amplitude * _slow_drift(n, sr, rng)
    return out


def _noise_band(n: int, sr: int, pitch_hz: float,
                rng: np.random.Generator) -> np.ndarray:
    """Pink-ish noise squeezed into a band around the pitch.

    Built in the frequency domain rather than with an IIR filter, because a
    resonant bandpass rung by noise is a very easy way to produce a whistle,
    and a whistle at 3 AM is the opposite of the brief.
    """
    spectrum = np.fft.rfft(rng.standard_normal(n).astype(np.float32))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    # A wide, gentle bell around the pitch — roughly an octave either side.
    with np.errstate(divide="ignore", invalid="ignore"):
        octaves = np.log2(np.maximum(freqs, 1e-6) / max(pitch_hz, 1e-6))
    shape = np.exp(-0.5 * (octaves / 0.8) ** 2)
    shape[freqs < 20.0] = 0.0

    band = np.fft.irfft(spectrum * shape, n=n).astype(np.float32)
    return band * _slow_drift(n, sr, rng)


def render_voice(voice: Voice, sr: int, seed: int) -> AudioBuffer:
    """Generate one voice's raw material: stereo, faded, not yet decayed.

    The two channels are generated from the same draw with independent drift so
    the voice has some width without being two unrelated sounds.
    """
    n = max(voice.n_frames, 1)
    rng = iteration_rng(seed, voice.key, 0)

    if voice.texture == "drone":
        generate = _drone
    elif voice.texture == "noiseband":
        generate = _noise_band
    else:
        raise ValueError(f"unknown texture: {voice.texture!r}")

    left = generate(n, sr, voice.pitch_hz, rng)
    right = generate(n, sr, voice.pitch_hz, rng)
    stereo = np.stack([left, right], axis=1)

    peak = float(np.abs(stereo).max())
    if peak > 0:
        stereo = stereo * (_PEAK / peak)
    stereo *= _fade_envelope(n, sr)[:, None]

    return AudioBuffer(stereo.astype(np.float32), sr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_palette.py -q`
Expected: PASS, 19 passed

- [ ] **Step 5: Commit**

```bash
git add sleepmix/night/palette.py tests/test_night_palette.py
git commit -m "feat: two generators, neither of which is allowed to start"
```

---

### Task 6: The stream — blocks that do not need each other

**Files:**
- Create: `sleepmix/night/stream.py`
- Test: `tests/test_night_stream.py`

**Interfaces:**
- Consumes: `plan_voices`, `Voice`, `render_voice`, `arc_at`, `NightContext`; `sleepmix.disintegration.apply_decay`; `sleepmix.effects.apply_reverb`; `sleepmix.soundbed.colored_noise`; `sleepmix.config.ReverbConfig`, `SoundbedConfig`; `sleepmix.util.iteration_rng`, `db_to_amp`.
- Produces:
  - `BLOCK_S = 10.0`
  - `NightStream(ctx, sr=44100, block_s=BLOCK_S, reverb=None, bed=None)` with `block(index: int) -> AudioBuffer` and `block_frames: int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_stream.py`:

```python
"""Blocks, and the guarantee the whole architecture rests on.

Block N rendered on its own must be bit-identical to block N rendered after
its predecessors. If that ever stops holding, block independence was a hope
rather than a property — and the most likely cause is something live having
been routed into this module, which is exactly what the last test here forbids.
"""
import numpy as np
import pytest

from sleepmix.night.context import NightContext, Weather
from sleepmix.night.stream import BLOCK_S, NightStream

SR = 22050


def _context(seed: int = 3, length_s: float = 8 * 3600.0) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=length_s,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)


def _stream(**kwargs) -> NightStream:
    return NightStream(_context(**kwargs), sr=SR)


def test_a_block_is_the_length_and_shape_it_should_be():
    stream = _stream()
    block = stream.block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    assert block.n_channels == 2
    assert block.sr == SR


def test_a_block_rendered_alone_matches_one_rendered_in_sequence():
    """The invariant, asserted numerically rather than argued."""
    target = 37
    alone = NightStream(_context(), sr=SR).block(target)

    sequential = NightStream(_context(), sr=SR)
    for index in range(target + 1):
        produced = sequential.block(index)
    assert np.array_equal(alone.data, produced.data)


def test_far_apart_blocks_are_independent_too():
    """A block deep into the night must not need the seven hours before it."""
    deep = int(6 * 3600 / BLOCK_S)
    alone = NightStream(_context(), sr=SR).block(deep)
    again = NightStream(_context(), sr=SR).block(deep)
    assert np.array_equal(alone.data, again.data)


def test_blocks_are_reproducible_from_the_seed():
    a = NightStream(_context(seed=11), sr=SR).block(5)
    b = NightStream(_context(seed=11), sr=SR).block(5)
    assert np.array_equal(a.data, b.data)


def test_a_different_seed_gives_different_audio():
    a = NightStream(_context(seed=11), sr=SR).block(5)
    b = NightStream(_context(seed=12), sr=SR).block(5)
    assert not np.array_equal(a.data, b.data)


def test_nothing_clips():
    stream = _stream()
    for index in (0, 3, 40, 400):
        assert np.abs(stream.block(index).data).max() <= 1.0


def test_the_late_night_is_quieter_than_the_early_night():
    stream = _stream()
    early = np.sqrt(np.mean(stream.block(6).data ** 2))
    late = np.sqrt(np.mean(stream.block(int(7 * 3600 / BLOCK_S)).data ** 2))
    assert late < early


def test_consecutive_blocks_join_without_a_step():
    """A discontinuity at a block seam is a click, and a click wakes people."""
    stream = _stream()
    first, second = stream.block(12), stream.block(13)
    step = np.abs(second.data[0] - first.data[-1]).max()
    within = np.abs(np.diff(first.data, axis=0)).max()
    assert step <= within * 4.0


def test_a_block_past_the_end_of_the_night_still_renders():
    """The arc clamps rather than ending, so the stream never runs out."""
    stream = _stream()
    block = stream.block(int(20 * 3600 / BLOCK_S))
    assert block.n_frames == int(BLOCK_S * SR)


def test_the_voice_cache_does_not_grow_without_bound():
    stream = _stream()
    for index in range(300):
        stream.block(index)
    assert len(stream._cache) <= 24


def test_the_stream_never_touches_a_speech_source():
    """Nothing live may enter the deterministic layer."""
    import sleepmix.night.stream as stream_module
    source = open(stream_module.__file__).read()
    assert "speech" not in source.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_stream.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.stream'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/stream.py`:

```python
"""Block assembly: the deterministic half of the night, entire.

Nothing live reaches this module and nothing live may be added to it. That is
the boundary the design's central invariant is drawn at — a block of *music*
rendered in isolation is bit-identical to the same block rendered in sequence —
and it is only checkable because the speech layer is mixed at playback instead
of here.

**A voice is rendered once, whole, and then sliced.** Blocks are seconds and
voices are minutes, so every voice spans several blocks. Teaching the decay
engine to render part of a placement would mean changing the contract at the
heart of this codebase; rendering the voice complete and slicing it costs a
bounded amount of memory (see ``_CACHE_BYTES`` — a single voice is tens of
megabytes, not the whole cache) and changes nothing. It also solves the
reverb problem for
free: reverb is applied to the *whole* voice before it is cached, so the tail
lives inside the cached buffer and survives being sliced. No block is ever
reverbed, so no reverb tail is ever cut off at a seam.

**A voice is decayed at ``progress = 1.0``, and the arc supplies the
endpoints.** ``plan.py`` builds each voice's ``StemDecayConfig`` with
``lowpass_end_hz`` and ``amp_end_db`` set from the ceilings at its birth, so
applying the decay fully puts the voice exactly where the night permits. The
descent across the night comes from successive voices being built under lower
ceilings — not from any voice decaying within itself.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

from ..audio import AudioBuffer
from ..config import ReverbConfig, SoundbedConfig
from ..disintegration import apply_decay
from ..effects import apply_reverb
from ..soundbed import colored_noise
from ..util import db_to_amp, iteration_rng
from .clock import arc_at
from .context import NightContext
from .palette import render_voice
from .plan import Voice, plan_voices

BLOCK_S = 10.0

# How many rendered voices to keep. A voice is at most four minutes, blocks are
# ten seconds, and a handful sound at once — so this holds every voice that can
# still be needed several times over, and evicts in birth order.
_CACHE_SIZE = 24

# Reverb tail kept past a voice's death, so the room does not stop with it.
_TAIL_S = 6.0

# The bed's level is scaled by the arc alongside everything else, and pushed
# further by weather: a wet night sounds wet.
_BED_BASE_DB = -34.0
_BED_RAIN_BOOST_DB = 6.0


class NightStream:
    """The music layer, addressable one block at a time.

    ``block(i)`` is a pure function of ``(ctx, sr, block_s, i)``. The cache is
    an optimisation and is never allowed to be an input: evicting it changes
    nothing about what comes out, which the tests check by rendering the same
    block from two different instances.
    """

    def __init__(self, ctx: NightContext, sr: int = 44100,
                 block_s: float = BLOCK_S,
                 reverb: ReverbConfig | None = None,
                 bed: SoundbedConfig | None = None) -> None:
        self.ctx = ctx
        self.sr = sr
        self.block_frames = int(block_s * sr)
        self.reverb = reverb if reverb is not None else ReverbConfig()
        self.bed = bed if bed is not None else SoundbedConfig()
        self._cache: OrderedDict[int, AudioBuffer] = OrderedDict()

    # -- voices ---------------------------------------------------------
    def _rendered(self, voice: Voice) -> AudioBuffer:
        """This voice, generated, decayed and reverbed, with its tail."""
        cached = self._cache.get(voice.index)
        if cached is not None:
            self._cache.move_to_end(voice.index)
            return cached

        raw = render_voice(voice, self.sr, self.ctx.seed)

        tail = int(_TAIL_S * self.sr)
        padded = AudioBuffer(
            np.pad(raw.data, ((0, tail), (0, 0))).astype(np.float32), self.sr)

        rng = iteration_rng(self.ctx.seed, voice.key, 1)
        decayed = apply_decay(padded, 1.0, voice.decay, rng)
        wet = apply_reverb(decayed, self.reverb)

        self._cache[voice.index] = wet
        self._cache.move_to_end(voice.index)
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return wet

    # -- bed ------------------------------------------------------------
    def _bed(self, index: int) -> np.ndarray:
        """A block of noise bed, keyed by block so it stays independent.

        Only noise, never the binaural tone: a tone generated per block would
        restart its phase at every seam and click. Binaural belongs to a later
        plan that can carry absolute time into the generator.
        """
        if self.bed.noise_type in (None, "", "none"):
            return np.zeros((self.block_frames, 2), dtype=np.float32)

        arc = arc_at(index * self.block_frames / self.sr, self.ctx)
        weather = self.ctx.weather
        wetness = min(weather.precipitation_mm / 8.0, 1.0)
        level_db = (_BED_BASE_DB
                    + _BED_RAIN_BOOST_DB * wetness
                    + arc.level_db)

        rng = iteration_rng(self.ctx.seed, "night:bed", index)
        mono = colored_noise(self.block_frames, self.sr,
                             self.bed.noise_type, rng)
        return (mono * db_to_amp(level_db)).astype(np.float32)[:, None] \
            * np.ones((1, 2), dtype=np.float32)

    # -- blocks ---------------------------------------------------------
    def block(self, index: int) -> AudioBuffer:
        """Assemble block ``index``, needing nothing that came before it."""
        start = index * self.block_frames
        end = start + self.block_frames
        out = np.zeros((self.block_frames, 2), dtype=np.float32)

        # A voice's reverb tail can reach a block its plan entry does not, so
        # the query window is widened by the tail rather than by guesswork.
        tail = int(_TAIL_S * self.sr)
        for voice in plan_voices(self.ctx, self.sr, max(start - tail, 0), end):
            rendered = self._rendered(voice)
            take_from = max(start - voice.birth_frame, 0)
            take_to = min(end - voice.birth_frame, rendered.n_frames)
            if take_to <= take_from:
                continue
            chunk = rendered.data[take_from:take_to]
            offset = max(voice.birth_frame - start, 0)
            out[offset:offset + len(chunk)] += chunk

        out += self._bed(index)
        return AudioBuffer(np.clip(out, -1.0, 1.0), self.sr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_stream.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Listen to it, because no test can hear**

Write a throwaway script and play the result. This is the first point in the plan where the thing exists as sound, and the arc's endpoints are taste values no assertion can judge.

```bash
pipenv run python - <<'PY'
from datetime import datetime, timezone
from sleepmix.audio import save_audio, AudioBuffer
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.stream import NightStream, BLOCK_S
import numpy as np

ctx = NightContext(seed=1, night_length_s=8*3600.0,
                   weather=Weather(0.5, 0.0, 3.0, 1013.25, 0.0),
                   moon_phase=0.5, day_length_h=12.0)
stream = NightStream(ctx, sr=44100)

for label, hour in [("2230", 0.0), ("0100", 2.5), ("0400", 5.5)]:
    first = int(hour * 3600 / BLOCK_S)
    blocks = [stream.block(first + i).data for i in range(18)]  # 3 minutes
    save_audio(AudioBuffer(np.concatenate(blocks), 44100), f"night-{label}.wav")
    print(f"wrote night-{label}.wav")
PY
```

Listen to all three. What you are judging: does it get quieter and sparser without getting *duller*; is there anything that reads as an event; is 04:00 still interesting or has it gone to nothing too early. Record what you changed, if anything, in the commit message.

- [ ] **Step 6: Commit**

```bash
git add sleepmix/night/stream.py tests/test_night_stream.py
git commit -m "feat: blocks that do not need each other"
```

---

### Task 7: The speech layer — a room through a wall

**Files:**
- Create: `sleepmix/night/speech.py`
- Test: `tests/test_night_speech.py`

**Interfaces:**
- Consumes: `sleepmix.audio.AudioBuffer`, `load_audio`, `silence`; `sleepmix.effects.apply_reverb`; `sleepmix.config.ReverbConfig`; `sleepmix.util.db_to_amp`.
- Produces:
  - `SpeechSource` protocol: `read(n_frames: int) -> AudioBuffer`, `close() -> None`
  - `SilentSource(sr: int, channels: int = 2)`
  - `RoomSource(paths: list[str], sr: int)` — loops through the files forever
  - `through_a_wall(buf: AudioBuffer, intelligibility: float) -> AudioBuffer`
  - `room_sources_from(directory: str, sr: int) -> SpeechSource`

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_speech.py`:

```python
"""A room heard through a wall.

The thing being built here is not "quiet dialogue" — it is the sound of a TV
on in the living room while you fall asleep on the couch. The tests below
mostly check that the treatment removes what makes speech followable, because
that is the property the whole design turns on: intelligible speech at 3 AM is
the failure mode of the project.
"""
import numpy as np
import pytest
import soundfile as sf

from sleepmix.audio import AudioBuffer
from sleepmix.night.speech import (
    RoomSource, SilentSource, room_sources_from, through_a_wall,
)

SR = 22050


def _write_tone(path, seconds=2.0, freq=440.0, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return path


def _broadband(n=SR * 2, sr=SR):
    rng = np.random.default_rng(0)
    x = rng.standard_normal((n, 2)).astype(np.float32) * 0.3
    return AudioBuffer(x, sr)


def test_a_silent_source_returns_exactly_what_was_asked_for():
    source = SilentSource(SR)
    buf = source.read(1234)
    assert buf.n_frames == 1234
    assert buf.n_channels == 2
    assert np.all(buf.data == 0.0)


def test_a_room_source_returns_the_requested_length(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    assert source.read(5000).n_frames == 5000


def test_a_room_source_keeps_going_past_the_end_of_its_file(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=0.5)
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    buf = source.read(int(SR * 3))
    assert buf.n_frames == int(SR * 3)
    # It looped rather than trailing off into silence.
    assert np.abs(buf.data[-1000:]).max() > 0.01


def test_a_room_source_advances_rather_than_repeating_the_same_window(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=4.0)
    source = RoomSource([str(tmp_path / "a.wav")], SR)
    first, second = source.read(2000), source.read(2000)
    assert not np.array_equal(first.data, second.data)


def test_a_room_source_moves_on_to_the_next_file(tmp_path):
    _write_tone(tmp_path / "a.wav", seconds=0.5, freq=200.0)
    _write_tone(tmp_path / "b.wav", seconds=0.5, freq=900.0)
    source = RoomSource([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], SR)
    buf = source.read(int(SR * 1.0))
    spectrum = np.abs(np.fft.rfft(buf.data.mean(axis=1)))
    freqs = np.fft.rfftfreq(buf.n_frames, 1.0 / SR)
    # Both files contributed, so both tones are present.
    assert spectrum[np.argmin(np.abs(freqs - 200.0))] > spectrum.mean() * 5
    assert spectrum[np.argmin(np.abs(freqs - 900.0))] > spectrum.mean() * 5


def test_a_missing_file_does_not_stop_the_night(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = RoomSource([str(tmp_path / "gone.wav"), str(tmp_path / "a.wav")],
                        SR)
    assert source.read(4000).n_frames == 4000


def test_a_source_with_nothing_readable_goes_silent(tmp_path):
    source = RoomSource([str(tmp_path / "nope.wav")], SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.all(buf.data == 0.0)


def test_room_sources_from_an_empty_directory_is_silent(tmp_path):
    source = room_sources_from(str(tmp_path), SR)
    assert isinstance(source, SilentSource)


def test_room_sources_from_a_missing_directory_is_silent(tmp_path):
    source = room_sources_from(str(tmp_path / "nothing-here"), SR)
    assert isinstance(source, SilentSource)


def test_room_sources_from_a_populated_directory_reads_it(tmp_path):
    _write_tone(tmp_path / "a.wav")
    source = room_sources_from(str(tmp_path), SR)
    assert isinstance(source, RoomSource)


def _high_frequency_share(buf: AudioBuffer) -> float:
    mono = buf.data.mean(axis=1)
    spectrum = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / buf.sr)
    above = spectrum[freqs > 1500.0].sum()
    return float(above / max(spectrum.sum(), 1e-12))


def test_through_a_wall_removes_the_frequencies_speech_is_carried_on():
    dry = _broadband()
    muffled = through_a_wall(dry, intelligibility=0.8)
    assert _high_frequency_share(muffled) < _high_frequency_share(dry) / 10.0


def test_lower_intelligibility_is_more_muffled():
    dry = _broadband()
    clearer = through_a_wall(dry, intelligibility=0.8)
    murkier = through_a_wall(dry, intelligibility=0.05)
    assert _high_frequency_share(murkier) <= _high_frequency_share(clearer)


def test_lower_intelligibility_is_quieter():
    dry = _broadband()
    clearer = through_a_wall(dry, intelligibility=0.8)
    murkier = through_a_wall(dry, intelligibility=0.05)
    assert np.abs(murkier.data).max() < np.abs(clearer.data).max()


def test_through_a_wall_preserves_length_and_shape():
    dry = _broadband()
    out = through_a_wall(dry, 0.5)
    assert out.n_frames == dry.n_frames
    assert out.n_channels == 2


def test_through_a_wall_survives_silence():
    quiet = AudioBuffer(np.zeros((1000, 2), dtype=np.float32), SR)
    out = through_a_wall(quiet, 0.5)
    assert np.all(np.isfinite(out.data))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_speech.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.speech'`

- [ ] **Step 3: Write the implementation**

Create `sleepmix/night/speech.py`:

```python
"""Human presence without a claim on you.

A police scanner and a sitcom you have seen forty times are opposite routes to
the same destination. The scanner is unfollowable *through obscurity* — clipped,
coded, half-buried in static. A comfort show is unfollowable *through
familiarity* — you already know how the scene ends, and the laugh track is a
room full of people being fine. Both remove narrative tension; neither asks for
attention. This module implements both doors.

The treatments differ and both are about distance. Radio is distant in space
(Task 8). A room is distant *through a wall*, which is not a workaround for the
fact that dialogue is intelligible but the actual thing being reproduced: a TV
on in the living room while you fall asleep on the couch.

Every source here is read by the *player*, never by ``stream.py``. That is the
boundary the block-independence invariant is drawn at.
"""
from __future__ import annotations

import os
from typing import Protocol

import numpy as np

from ..audio import AudioBuffer, load_audio
from ..config import ReverbConfig
from ..effects import apply_reverb
from ..util import db_to_amp

_MEDIA_SUFFIXES = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aif", ".aiff")

# The wall. A gentle slope from here down, moving lower as the night goes on.
_WALL_CLEAR_HZ = 900.0
_WALL_MURKY_HZ = 380.0

# How loud a room is allowed to be, relative to full scale, at each end of the
# intelligibility range.
_ROOM_CLEAR_DB = -26.0
_ROOM_MURKY_DB = -42.0

# A small room, not the cavern the stems sit in.
_WALL_REVERB = ReverbConfig(room_size=0.45, damping=0.75, wet=0.25, dry=0.85,
                            width=0.6, predelay_ms=12.0)


class SpeechSource(Protocol):
    """Something that can always produce ``n_frames`` more of audio.

    ``read`` may never raise and may never block indefinitely: it is called
    from the playback path, where the only acceptable failure is silence.
    Implementations catch their own errors and return quiet rather than
    propagating.
    """

    def read(self, n_frames: int) -> AudioBuffer: ...

    def close(self) -> None: ...


class SilentSource:
    """The fallback every other source degrades into."""

    def __init__(self, sr: int, channels: int = 2) -> None:
        self.sr = sr
        self.channels = channels

    def read(self, n_frames: int) -> AudioBuffer:
        return AudioBuffer(
            np.zeros((n_frames, self.channels), dtype=np.float32), self.sr)

    def close(self) -> None:
        return None


class RoomSource:
    """Media the operator already owns, played end to end and then again.

    Files are decoded lazily, one at a time, and a file that fails to decode is
    skipped rather than raised — a corrupt download in the room directory
    should cost one file, not the night. If none of them can be read at all,
    every ``read`` returns silence and the player carries on with music.
    """

    def __init__(self, paths: list[str], sr: int) -> None:
        self.paths = list(paths)
        self.sr = sr
        self._index = 0
        self._buffer: AudioBuffer | None = None
        self._cursor = 0
        self._exhausted = False

    def _advance(self) -> bool:
        """Load the next readable file. False when none of them are."""
        for _ in range(len(self.paths)):
            path = self.paths[self._index % len(self.paths)]
            self._index += 1
            try:
                self._buffer = load_audio(path, sr=self.sr).to_stereo()
                self._cursor = 0
                return True
            except Exception:
                continue
        return False

    def read(self, n_frames: int) -> AudioBuffer:
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if self._exhausted or not self.paths:
            return AudioBuffer(out, self.sr)

        filled = 0
        while filled < n_frames:
            if self._buffer is None or self._cursor >= self._buffer.n_frames:
                if not self._advance():
                    self._exhausted = True
                    break
            assert self._buffer is not None
            take = min(n_frames - filled,
                       self._buffer.n_frames - self._cursor)
            out[filled:filled + take] = \
                self._buffer.data[self._cursor:self._cursor + take]
            self._cursor += take
            filled += take

        return AudioBuffer(out, self.sr)

    def close(self) -> None:
        self._buffer = None


def room_sources_from(directory: str, sr: int) -> SpeechSource:
    """Whatever is in the room directory, or silence.

    Zero options is the whole point of Phase 1, so the way a comfort show gets
    into a night is by being dropped into a folder rather than named on a
    command line.
    """
    try:
        names = sorted(
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(_MEDIA_SUFFIXES)
        )
    except OSError:
        names = []
    return RoomSource(names, sr) if names else SilentSource(sr)


def _lowpass_fft(x: np.ndarray, cutoff_hz: float, sr: int) -> np.ndarray:
    """A gentle, phase-linear roll-off from ``cutoff_hz`` upward.

    Done in the frequency domain with a soft shoulder rather than with a steep
    IIR, because a wall is not a brick-wall filter and a resonant one would
    add a colour that reads as an effect.
    """
    n = len(x)
    spectrum = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    with np.errstate(divide="ignore", invalid="ignore"):
        octaves_above = np.log2(np.maximum(freqs, 1e-6) / max(cutoff_hz, 1e-6))
    shape = np.where(octaves_above <= 0, 1.0, 2.0 ** (-1.6 * octaves_above))
    return np.fft.irfft(spectrum * shape[:, None], n=n).astype(np.float32)


def through_a_wall(buf: AudioBuffer, intelligibility: float) -> AudioBuffer:
    """Put a room on the other side of a wall.

    ``intelligibility`` runs 0..1 and comes from the night arc, so this gets
    murkier and quieter of its own accord as the night goes on. Both the cutoff
    and the level move with it: a distant room is not just a quiet one.
    """
    amount = float(min(max(intelligibility, 0.0), 1.0))
    cutoff = _WALL_MURKY_HZ + (_WALL_CLEAR_HZ - _WALL_MURKY_HZ) * amount
    level_db = _ROOM_MURKY_DB + (_ROOM_CLEAR_DB - _ROOM_MURKY_DB) * amount

    muffled = _lowpass_fft(buf.to_stereo().data, cutoff, buf.sr)
    walled = apply_reverb(AudioBuffer(muffled, buf.sr), _WALL_REVERB)

    data = walled.data[:buf.n_frames]
    if len(data) < buf.n_frames:
        data = np.pad(data, ((0, buf.n_frames - len(data)), (0, 0)))

    peak = float(np.abs(data).max())
    if peak > 0:
        data = data * (db_to_amp(level_db) / peak)
    return AudioBuffer(data.astype(np.float32), buf.sr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_speech.py -q`
Expected: PASS, 15 passed

- [ ] **Step 5: Commit**

```bash
git add sleepmix/night/speech.py tests/test_night_speech.py
git commit -m "feat: a room heard through a wall"
```

---

### Task 8: The radio — a squelch, and static that is doing work

**Files:**
- Modify: `sleepmix/night/speech.py` (add `RadioSource`, `squelch`, `over_the_air`)
- Test: `tests/test_night_speech_radio.py`

**Interfaces:**
- Consumes: everything from Task 7.
- Produces:
  - `squelch(x: np.ndarray, sr: int, floor_rms: float, open_ratio: float = 3.0) -> np.ndarray` — a 0..1 gain envelope
  - `over_the_air(buf: AudioBuffer, intelligibility: float, static_gain: float) -> AudioBuffer`
  - `RadioSource(url: str, sr: int, chunk_s: float = 1.0)`
  - `radio_source_from(url: str | None, sr: int) -> SpeechSource`

> **Note on transport.** See "Deviation from the spec" at the top of this plan. `RadioSource` reads an HTTP/Icecast audio stream. A `KiwiSource` speaking the KiwiSDR websocket protocol implements the same interface and is a follow-up; nothing else in the night changes when it lands.

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_speech_radio.py`:

```python
"""The squelch, the static, and a network that is allowed to fail.

The reason radio is worth the trouble is that it gates itself: HF is already
transmissions separated by silence and static, so the sparseness that makes
YALT work does not have to be simulated by a timer. These tests are mostly
about that gate behaving like a squelch rather than like a noise gate on a
vocal — it must let the static through underneath, because the static is the
part the operator specifically asked for.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night import speech as speech_mod
from sleepmix.night.speech import (
    RadioSource, SilentSource, over_the_air, radio_source_from, squelch,
)

SR = 22050


def _transmission_over_static(sr=SR):
    """Two seconds of static with a loud burst in the middle second."""
    rng = np.random.default_rng(1)
    x = rng.standard_normal(2 * sr).astype(np.float32) * 0.02
    t = np.arange(sr) / sr
    x[sr // 2: sr // 2 + sr] += (0.4 * np.sin(2 * np.pi * 600 * t)
                                 ).astype(np.float32)
    return x


def test_the_squelch_opens_on_a_transmission_and_closes_after_it():
    x = _transmission_over_static()
    gate = squelch(x, SR, floor_rms=0.02)
    during = gate[SR: SR + SR // 2].mean()
    between = gate[: SR // 4].mean()
    assert during > 0.8
    assert between < 0.2


def test_the_squelch_envelope_is_smooth():
    """A gate that snaps is a click, and a click wakes people."""
    gate = squelch(_transmission_over_static(), SR, floor_rms=0.02)
    assert np.abs(np.diff(gate)).max() < 0.01


def test_the_squelch_stays_in_range():
    gate = squelch(_transmission_over_static(), SR, floor_rms=0.02)
    assert gate.min() >= 0.0
    assert gate.max() <= 1.0


def test_pure_static_never_opens_the_gate():
    rng = np.random.default_rng(2)
    x = (rng.standard_normal(2 * SR) * 0.02).astype(np.float32)
    assert squelch(x, SR, floor_rms=0.02).mean() < 0.2


def test_over_the_air_keeps_the_static_underneath_the_gate():
    """The static is the point, not a side effect to be gated away."""
    buf = AudioBuffer(np.stack([_transmission_over_static()] * 2, axis=1), SR)
    out = over_the_air(buf, intelligibility=0.8, static_gain=0.25)
    quiet_part = np.abs(out.data[: SR // 4]).max()
    assert quiet_part > 0.0


def test_over_the_air_is_band_limited():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((SR, 2)).astype(np.float32) * 0.3
    out = over_the_air(AudioBuffer(x, SR), intelligibility=0.8,
                       static_gain=0.2)
    spectrum = np.abs(np.fft.rfft(out.data.mean(axis=1))) ** 2
    freqs = np.fft.rfftfreq(out.n_frames, 1.0 / SR)
    above = spectrum[freqs > 4000.0].sum() / max(spectrum.sum(), 1e-12)
    below = spectrum[freqs < 200.0].sum() / max(spectrum.sum(), 1e-12)
    assert above < 0.02
    assert below < 0.05


def test_lower_intelligibility_is_quieter():
    buf = AudioBuffer(np.stack([_transmission_over_static()] * 2, axis=1), SR)
    clear = over_the_air(buf, 0.8, 0.2)
    murky = over_the_air(buf, 0.05, 0.2)
    assert np.abs(murky.data).max() < np.abs(clear.data).max()


def test_over_the_air_preserves_length():
    buf = AudioBuffer(np.zeros((5000, 2), dtype=np.float32), SR)
    assert over_the_air(buf, 0.5, 0.2).n_frames == 5000


def test_a_radio_source_that_cannot_connect_reads_as_silence(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(speech_mod, "_open_stream", refuse)
    source = RadioSource("http://example.invalid/stream", SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.all(buf.data == 0.0)


def test_a_radio_source_that_dies_mid_night_reads_as_silence(monkeypatch):
    class DyingStream:
        def __init__(self):
            self.calls = 0

        def read(self, n_frames):
            self.calls += 1
            if self.calls > 1:
                raise OSError("stream dropped")
            return np.full((n_frames, 2), 0.1, dtype=np.float32)

        def close(self):
            return None

    monkeypatch.setattr(speech_mod, "_open_stream", lambda *a, **k: DyingStream())
    source = RadioSource("http://example.invalid/stream", SR)
    assert np.abs(source.read(1000).data).max() > 0.0
    second = source.read(1000)
    assert second.n_frames == 1000
    assert np.all(second.data == 0.0)


def test_radio_source_from_none_is_silent():
    assert isinstance(radio_source_from(None, SR), SilentSource)


def test_radio_source_from_empty_string_is_silent():
    assert isinstance(radio_source_from("", SR), SilentSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_speech_radio.py -q`
Expected: FAIL — `ImportError: cannot import name 'squelch' from 'sleepmix.night.speech'`

- [ ] **Step 3: Write the implementation**

Append to `sleepmix/night/speech.py`:

```python
# -- radio ----------------------------------------------------------------
#
# The other door: unfollowable through obscurity rather than familiarity. HF
# and scanner audio is already intermittent, so the sparseness this design
# wants does not have to be invented — it is a property of the signal, and the
# gate below simply lets it through.

# Roughly telephone bandwidth: what a distant transmission survives as.
_AIR_LOW_HZ = 300.0
_AIR_HIGH_HZ = 3000.0

_AIR_CLEAR_DB = -24.0
_AIR_MURKY_DB = -40.0

_SQUELCH_SMOOTH_S = 0.05
_STREAM_CHUNK_S = 1.0


def squelch(x: np.ndarray, sr: int, floor_rms: float,
            open_ratio: float = 3.0) -> np.ndarray:
    """A 0..1 envelope that opens where the signal rises above the noise.

    Not a noise gate: the output is an envelope the caller *blends* with, so
    the static underneath can be kept at a lower level rather than removed.
    Removing it would throw away the part of a scanner feed that is doing the
    most work.

    Smoothed with a one-pole filter run forwards and then backwards, so the
    gate has no attack and no phase shift. A gate that snaps is a click, and a
    click at 3 AM is the thing this whole program is arranged around avoiding.
    """
    from scipy.signal import lfilter

    mono = x.mean(axis=1) if x.ndim == 2 else x
    threshold = max(floor_rms, 1e-9) * open_ratio
    raw = (np.abs(mono) > threshold).astype(np.float32)

    alpha = float(np.exp(-1.0 / max(_SQUELCH_SMOOTH_S * sr, 1.0)))
    forward = lfilter([1.0 - alpha], [1.0, -alpha], raw)
    backward = lfilter([1.0 - alpha], [1.0, -alpha], forward[::-1])[::-1]
    return np.clip(backward, 0.0, 1.0).astype(np.float32)


def _bandpass_fft(x: np.ndarray, low_hz: float, high_hz: float,
                  sr: int) -> np.ndarray:
    """Soft-shouldered band limiting, in the frequency domain."""
    n = len(x)
    spectrum = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    with np.errstate(divide="ignore", invalid="ignore"):
        below = np.log2(np.maximum(freqs, 1e-6) / max(low_hz, 1e-6))
        above = np.log2(np.maximum(freqs, 1e-6) / max(high_hz, 1e-6))
    shape = (np.where(below >= 0, 1.0, 2.0 ** (2.0 * below))
             * np.where(above <= 0, 1.0, 2.0 ** (-2.0 * above)))
    return np.fft.irfft(spectrum * shape[:, None], n=n).astype(np.float32)


def over_the_air(buf: AudioBuffer, intelligibility: float,
                 static_gain: float) -> AudioBuffer:
    """Put a transmission at the far end of an ionospheric path.

    The gate is applied as a *blend* rather than a mute: where it is open the
    transmission is at full weight, and where it is closed the same audio
    survives at ``static_gain``. Since what is there when the gate is closed is
    static, that is exactly the sparse-voices-over-hiss texture this is for.
    """
    amount = float(min(max(intelligibility, 0.0), 1.0))
    level_db = _AIR_MURKY_DB + (_AIR_CLEAR_DB - _AIR_MURKY_DB) * amount

    stereo = buf.to_stereo().data
    limited = _bandpass_fft(stereo, _AIR_LOW_HZ, _AIR_HIGH_HZ, buf.sr)

    floor = float(np.sqrt(np.mean(limited ** 2))) if limited.size else 0.0
    gate = squelch(limited, buf.sr, floor_rms=max(floor, 1e-6))
    blended = limited * (static_gain + (1.0 - static_gain) * gate[:, None])

    peak = float(np.abs(blended).max())
    if peak > 0:
        blended = blended * (db_to_amp(level_db) / peak)
    return AudioBuffer(blended.astype(np.float32), buf.sr)


def _open_stream(url: str, sr: int):
    """Open an HTTP audio stream and return something with ``read``/``close``.

    Imported inside the function per the graceful-degradation policy, and
    factored out so tests can replace the network without patching a library
    they do not otherwise care about.
    """
    import soundfile as sf
    import requests

    response = requests.get(url, stream=True, timeout=10)
    response.raise_for_status()

    handle = sf.SoundFile(response.raw, mode="r")

    class _Stream:
        def read(self, n_frames: int) -> np.ndarray:
            data = handle.read(n_frames, dtype="float32", always_2d=True)
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            return data[:, :2]

        def close(self) -> None:
            handle.close()
            response.close()

    return _Stream()


class RadioSource:
    """A live HTTP audio stream, or silence.

    Every failure mode — refused connection, DNS, a stream that stops
    mid-night, a decoder that gives up — lands in the same place: this source
    goes permanently quiet and the player carries on with music. Reconnection
    is deliberately not attempted here. A retry loop inside the playback path
    is a stall inside the playback path, and there is no version of "the
    network came back" that is worth a gap in the audio at 3 AM.
    """

    def __init__(self, url: str, sr: int, chunk_s: float = _STREAM_CHUNK_S) -> None:
        self.url = url
        self.sr = sr
        self.chunk_frames = int(chunk_s * sr)
        self._stream = None
        self._opened = False
        self._dead = False

    def _ensure_open(self) -> bool:
        if self._dead:
            return False
        if self._opened:
            return self._stream is not None
        self._opened = True
        try:
            self._stream = _open_stream(self.url, self.sr)
            return True
        except Exception:
            self._dead = True
            return False

    def read(self, n_frames: int) -> AudioBuffer:
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if not self._ensure_open():
            return AudioBuffer(out, self.sr)

        try:
            filled = 0
            while filled < n_frames:
                chunk = self._stream.read(min(self.chunk_frames,
                                              n_frames - filled))
                if chunk is None or len(chunk) == 0:
                    raise OSError("stream ended")
                take = min(len(chunk), n_frames - filled)
                out[filled:filled + take] = chunk[:take]
                filled += take
        except Exception:
            self._dead = True
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            return AudioBuffer(np.zeros((n_frames, 2), dtype=np.float32),
                               self.sr)

        return AudioBuffer(out, self.sr)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._dead = True


def radio_source_from(url: str | None, sr: int) -> SpeechSource:
    """A radio source for ``url``, or silence when none is configured."""
    return RadioSource(url, sr) if url else SilentSource(sr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_speech_radio.py tests/test_night_speech.py -q`
Expected: PASS, 27 passed

- [ ] **Step 5: Commit**

```bash
git add sleepmix/night/speech.py tests/test_night_speech_radio.py
git commit -m "feat: a squelch, and static that is doing work"
```

---

### Task 9: The player, and one button

**Files:**
- Create: `sleepmix/night/player.py`
- Modify: `sleepmix/cli.py` (add the `night` command)
- Test: `tests/test_night_player.py`

**Interfaces:**
- Consumes: `NightStream`, `BLOCK_S`, `arc_at`, `NightContext`, `build_context`, `SpeechSource`, `room_sources_from`, `radio_source_from`, `through_a_wall`, `over_the_air`; `sleepmix.paths.data_dir`; `sleepmix.soundbed.colored_noise`.
- Produces:
  - `NightPlayer(stream, room, radio, queue_depth=3)` with `mixed_block(index: int) -> AudioBuffer`, `fallback_block(index: int) -> AudioBuffer`, `run(max_blocks: int | None = None) -> None`
  - `room_directory() -> str`
  - `sleepmix night` CLI command

- [ ] **Step 1: Write the failing test**

Create `tests/test_night_player.py`:

```python
"""The player, which owns the two things that cannot be known in advance.

Everything here is tested without a sound device. ``run`` takes a sink so the
mixing, the degradation and the queue can be driven in a unit test; opening
the real device is one line inside the CLI command, which is the only part
nobody can assert.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.player import NightPlayer, room_directory
from sleepmix.night.speech import SilentSource
from sleepmix.night.stream import BLOCK_S, NightStream

SR = 22050


def _context(seed: int = 3) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=8 * 3600.0,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)


class LoudSource:
    """A speech source that always has something to say."""

    def __init__(self, sr: int, level: float = 0.5) -> None:
        self.sr = sr
        self.level = level
        self.closed = False

    def read(self, n_frames: int) -> AudioBuffer:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((n_frames, 2)).astype(np.float32) * self.level
        return AudioBuffer(x, self.sr)

    def close(self) -> None:
        self.closed = True


class ExplodingSource:
    def __init__(self, sr: int) -> None:
        self.sr = sr

    def read(self, n_frames: int) -> AudioBuffer:
        raise RuntimeError("the receiver fell over")

    def close(self) -> None:
        return None


def _player(room=None, radio=None, ctx=None) -> NightPlayer:
    ctx = ctx or _context()
    stream = NightStream(ctx, sr=SR)
    return NightPlayer(stream,
                       room or SilentSource(SR),
                       radio or SilentSource(SR))


def test_a_mixed_block_is_the_right_shape():
    block = _player().mixed_block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    assert block.n_channels == 2


def test_speech_actually_reaches_the_output():
    quiet = _player().mixed_block(3)
    loud = _player(room=LoudSource(SR)).mixed_block(3)
    assert not np.array_equal(quiet.data, loud.data)
    assert np.abs(loud.data).max() > np.abs(quiet.data).max()


def test_a_speech_source_that_raises_costs_only_its_own_voice():
    """Degrade silently: the music must survive the receiver falling over."""
    music_only = _player().mixed_block(4)
    with_broken_radio = _player(radio=ExplodingSource(SR)).mixed_block(4)
    assert np.array_equal(music_only.data, with_broken_radio.data)


def test_both_speech_sources_failing_still_produces_music():
    block = _player(room=ExplodingSource(SR),
                    radio=ExplodingSource(SR)).mixed_block(4)
    assert np.abs(block.data).max() > 0.0


def test_speech_gets_quieter_as_the_night_goes_on():
    """The intelligibility ceiling is read at mix time, so the two layers
    descend together rather than the music alone."""
    player = _player(room=LoudSource(SR))
    n = int(BLOCK_S * SR)
    early = np.abs(player._speech(6, n)).max()
    late = np.abs(player._speech(int(7 * 3600 / BLOCK_S), n)).max()
    assert late < early


def test_a_mixed_block_never_clips():
    player = _player(room=LoudSource(SR, level=1.0),
                     radio=LoudSource(SR, level=1.0))
    for index in (0, 5, 200):
        assert np.abs(player.mixed_block(index).data).max() <= 1.0


def test_the_fallback_block_is_quiet_noise_not_silence():
    """When the renderer cannot keep up, the player makes its own bed."""
    block = _player().fallback_block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    peak = np.abs(block.data).max()
    assert 0.0 < peak < 0.2


def test_run_delivers_the_blocks_it_was_asked_for():
    delivered = []
    _player().run(max_blocks=4, sink=delivered.append)
    assert len(delivered) == 4
    assert all(b.n_frames == int(BLOCK_S * SR) for b in delivered)


def test_run_falls_back_rather_than_stopping_when_rendering_fails():
    ctx = _context()
    stream = NightStream(ctx, sr=SR)
    broken = {"count": 0}

    def explode(index):
        broken["count"] += 1
        raise RuntimeError("render failed")

    stream.block = explode  # type: ignore[method-assign]
    player = NightPlayer(stream, SilentSource(SR), SilentSource(SR))

    delivered = []
    player.run(max_blocks=3, sink=delivered.append)
    assert len(delivered) == 3
    assert broken["count"] == 3
    assert all(np.abs(b.data).max() < 0.2 for b in delivered)


def test_run_closes_its_speech_sources():
    room = LoudSource(SR)
    _player(room=room).run(max_blocks=1, sink=lambda _b: None)
    assert room.closed


def test_the_room_directory_lives_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert str(tmp_path) in room_directory()
    assert room_directory().endswith("room")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pipenv run pytest tests/test_night_player.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleepmix.night.player'`

- [ ] **Step 3: Write the player**

Create `sleepmix/night/player.py`:

```python
"""Playback, and the two things that cannot be known in advance.

The renderer owns everything deterministic; this owns everything that is not.
That is one boundary, not two coincidences: live speech now, and the
microphone trim in Phase 2, are both things whose value at block *N* is not
knowable when block *N* is rendered. Putting them here is what lets
``stream.py`` keep the block-independence guarantee the whole design rests on.

**Nothing that goes wrong here may make a sound.** Every failure path ends in
less audio, never in different audio and never in a stop. A speech source that
raises loses its own voice and nothing else; a renderer that falls over is
replaced by a bed this module generates itself, which needs no plan and so is
available precisely when the thing that would have supplied one is the thing
that failed.
"""
from __future__ import annotations

import os
from typing import Callable

import numpy as np

from ..audio import AudioBuffer
from ..paths import data_dir
from ..soundbed import colored_noise
from ..util import db_to_amp, iteration_rng
from .clock import arc_at
from .speech import SpeechSource, over_the_air, through_a_wall
from .stream import NightStream

# How loud the player's own emergency bed is, before the arc scales it. Quiet
# enough to be a texture rather than an announcement that something is wrong.
_FALLBACK_BED_DB = -38.0

# How much of a radio feed's between-transmission static survives the gate.
_STATIC_GAIN = 0.22


def room_directory() -> str:
    """Where a comfort show goes. Created on demand.

    Phase 1 has no configuration, so the way media gets into a night is by
    being dropped into a folder rather than named on a command line.
    """
    path = os.path.join(str(data_dir()), "room")
    os.makedirs(path, exist_ok=True)
    return path


class NightPlayer:
    """Assemble the deterministic block, mix the live layer, hand it out."""

    def __init__(self, stream: NightStream, room: SpeechSource,
                 radio: SpeechSource, queue_depth: int = 3) -> None:
        self.stream = stream
        self.room = room
        self.radio = radio
        self.queue_depth = queue_depth

    # -- the live layer -------------------------------------------------
    def _speech(self, index: int, n_frames: int) -> np.ndarray:
        """Both speech sources, treated and summed. Never raises.

        The intelligibility ceiling is read here rather than at render time
        because this is where the speech is; the value comes from the same
        ``arc_at`` the renderer uses, so the two layers descend together.
        """
        arc = arc_at(index * self.stream.block_frames / self.stream.sr,
                     self.stream.ctx)
        out = np.zeros((n_frames, 2), dtype=np.float32)

        # Each source is paired with its own distance treatment: a room is
        # distant through a wall, a transmission is distant in space. The
        # try/except is per source, so one failing costs only its own voice.
        treated = (
            (self.room, lambda buf: through_a_wall(buf, arc.intelligibility)),
            (self.radio, lambda buf: over_the_air(buf, arc.intelligibility,
                                                  _STATIC_GAIN)),
        )
        for source, treat in treated:
            try:
                data = treat(source.read(n_frames)).to_stereo().data[:n_frames]
                out[:len(data)] += data
            except Exception:
                continue

        return out

    def mixed_block(self, index: int) -> AudioBuffer:
        """One block of music with the live layer summed on top."""
        music = self.stream.block(index)
        speech = self._speech(index, music.n_frames)
        mixed = np.clip(music.data + speech, -1.0, 1.0)
        return AudioBuffer(mixed.astype(np.float32), music.sr)

    # -- degradation ----------------------------------------------------
    def fallback_block(self, index: int) -> AudioBuffer:
        """A bed this module generates, for when the renderer cannot keep up.

        Deliberately does not go through ``NightStream``: the whole point is
        that this is available when the renderer is the thing that failed.
        """
        n = self.stream.block_frames
        sr = self.stream.sr
        arc = arc_at(index * n / sr, self.stream.ctx)
        rng = iteration_rng(self.stream.ctx.seed, "night:fallback", index)
        mono = colored_noise(n, sr, "pink", rng)
        level = db_to_amp(_FALLBACK_BED_DB + arc.level_db)
        data = (mono * level).astype(np.float32)[:, None] * np.ones((1, 2),
                                                                    np.float32)
        return AudioBuffer(np.clip(data, -1.0, 1.0), sr)

    # -- the loop -------------------------------------------------------
    def run(self, max_blocks: int | None = None,
            sink: Callable[[AudioBuffer], None] | None = None) -> None:
        """Produce blocks until ``max_blocks``, or forever.

        ``sink`` receives each block. The CLI passes one that writes to the
        sound device; the tests pass one that appends to a list, which is what
        makes every degradation path above assertable without hardware.
        """
        if sink is None:
            raise ValueError("run needs a sink to hand blocks to")

        index = 0
        try:
            while max_blocks is None or index < max_blocks:
                try:
                    block = self.mixed_block(index)
                except Exception:
                    block = self.fallback_block(index)
                sink(block)
                index += 1
        finally:
            for source in (self.room, self.radio):
                try:
                    source.close()
                except Exception:
                    pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pipenv run pytest tests/test_night_player.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Add the CLI command**

In `sleepmix/cli.py`, append this command after the existing `ui` command:

```python
@main.command()
@click.option("--seconds", type=int, default=None,
              help="Stop after this many seconds. For trying it out; a real "
                   "night takes no arguments at all.")
def night(seconds: int | None) -> None:
    """Play an indefinite, self-quieting ambient stream until morning.

    Deliberately takes no configuration. Location comes from SLEEPMIX_LAT and
    SLEEPMIX_LON (defaulting to Amsterdam), a comfort show comes from whatever
    is in the `room` folder under the data directory, and a radio feed comes
    from SLEEPMIX_RADIO_URL if one is set. Everything else is derived from the
    sky, the weather, and a seed.
    """
    import datetime as dt
    import os
    import random

    from .night.context import build_context
    from .night.player import NightPlayer, room_directory
    from .night.speech import radio_source_from, room_sources_from
    from .night.stream import BLOCK_S, NightStream

    lat = float(os.environ.get("SLEEPMIX_LAT", "52.3676"))
    lon = float(os.environ.get("SLEEPMIX_LON", "4.9041"))
    seed = int(os.environ.get("SLEEPMIX_SEED", random.randrange(2 ** 31)))
    sr = 44100

    ctx = build_context(dt.datetime.now(dt.timezone.utc), lat, lon, seed)
    stream = NightStream(ctx, sr=sr)
    player = NightPlayer(
        stream,
        room_sources_from(room_directory(), sr),
        radio_source_from(os.environ.get("SLEEPMIX_RADIO_URL"), sr),
    )

    click.echo(f"Night {seed}: {ctx.night_length_s / 3600:.1f} h until light.")
    click.echo(f"Room audio: {room_directory()}")
    click.echo("Ctrl-C to stop.")

    try:
        import sounddevice as sd
    except Exception:
        raise click.ClickException(
            'sounddevice is not installed — run: pip install "sleepmix[night]"')

    max_blocks = int(seconds / BLOCK_S) if seconds else None
    with sd.OutputStream(samplerate=sr, channels=2, dtype="float32") as out:
        try:
            player.run(max_blocks=max_blocks, sink=lambda b: out.write(b.data))
        except KeyboardInterrupt:
            pass
```

- [ ] **Step 6: Verify the command is wired up**

Run: `pipenv run sleepmix night --help`
Expected: the help text above, with `--seconds`

- [ ] **Step 7: Play it**

Run: `pipenv run sleepmix night --seconds 120`
Expected: two minutes of audio out of the speakers, no traceback, Ctrl-C stops it cleanly.

Then drop any audio file into the folder the command prints and run it again — you should hear it muffled underneath.

- [ ] **Step 8: Run the whole suite**

Run: `pipenv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 9: Commit**

```bash
git add sleepmix/night/player.py sleepmix/cli.py tests/test_night_player.py
git commit -m "feat: one button, and a night that comes out of it"
```

---

### Task 10: The documentation this project runs on

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/project-state.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

This task writes no application code. This repository's documentation carries the *reasoning* — `docs/architecture.md` for how the pieces fit and why the alternatives were rejected, `docs/project-state.md` for what is true right now and what was traded away — and a plan that ships code without it leaves the next reader to re-derive arguments that took a design cycle to settle.

- [ ] **Step 1: Add the architecture section**

In `docs/architecture.md`, add a new section after "The arrangement seam: placement is a plan, not a constant". Write it in the voice of the surrounding document — argue, name what was rejected, and be specific. It must cover:

- **The invariant, and that it is the purity property renamed.** Block *N* of the music must be renderable without rendering what precedes it. Say explicitly that this was engineered in for previews and turned out to be exactly what an indefinite stream needs.
- **Why the speech layer is excluded from that invariant**, and that the exclusion is what makes the guarantee testable rather than a hope. Live audio cannot be deterministic; putting it at playback is the whole answer.
- **The two nested clocks**, and the rule that a voice born at hour six may not start bright — including that this makes the descent a constraint on what may exist rather than an automation curve something louder could fight.
- **Why a voice is rendered whole, cached, and sliced** rather than teaching `apply_decay` to render partial placements, and that this also solves the reverb-tail-at-a-seam problem for free.
- **Why decay runs at `progress = 1.0`** with the arc supplying the endpoints, rather than each voice decaying within itself.
- **Why `plan.py` may not import audio**, pointing at the same rule `arrangement.py` lives by.
- **The three rejected architectures** — realtime DSP graph, long render with live layers, and (for speech) the harvested pool — each with the reason.

- [ ] **Step 2: Add the project-state section**

In `docs/project-state.md`, add a "Plan 5, Phase 1: the night" section at the top of the plan sections, covering:

- What shipped, and that it is synthesis-only by choice — the source-derived half is Phase 3 and the seam kept for it is that `Voice` names a *source of material*, not a generator. Record the risk stated in the spec: if this is good on its own, Phase 3 may never feel necessary, and the handover is harder to design retroactively.
- **The placeholders**, verbatim from the spec plus anything found while implementing: the night-length clamp bounds (`MIN_NIGHT_S`, `MAX_NIGHT_S`), `NEUTRAL_WEATHER`, the interval set and `ROOT_DESCENT_SEMITONES` in `plan.py`, and the four arc endpoints in `clock.py`. All are invented values, none is measured, and the person who can fix them is the one who sleeps through it.
- **The deviation from the spec**: `RadioSource` reads an HTTP stream, not a KiwiSDR websocket, and why (the protocol could not be specified without reading the library first). A `KiwiSource` on the same interface is the follow-up.
- **Binaural beats are not in the night bed**, because a tone generated per block restarts its phase at every seam and clicks. Needs absolute time carried into the generator; deferred rather than broken.
- **`RadioSource` never reconnects.** A retry loop inside the playback path is a stall inside the playback path. A dropped feed is permanent for that night, by choice. If this proves too blunt in practice, the fix is a reconnect on a background thread that swaps a source in — not a retry where it currently fails.
- Whatever the Task 6 listening pass changed, and what it sounded like.

- [ ] **Step 3: Add the README section**

In `README.md`, add a short section after the render documentation:

- `pip install "sleepmix[night]"`, then `sleepmix night`.
- The three environment variables (`SLEEPMIX_LAT`, `SLEEPMIX_LON`, `SLEEPMIX_RADIO_URL`) and that they are the only configuration there is, on purpose.
- The room folder: drop a comfort show in it and it plays through a wall.
- That it stops on its own and takes no arguments, and that `--seconds` exists only for trying it out.

- [ ] **Step 4: Verify nothing in the docs contradicts the code**

Run: `pipenv run pytest -q`

Then re-read each claim written in Steps 1–3 against the module it describes. Specifically check that every constant named in the placeholder list still exists under that name, and that the environment variables named in the README match the ones `cli.py` actually reads.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md docs/project-state.md README.md
git commit -m "docs: the night, its invariant, and the values nobody has slept on"
```

---

## Self-review

**Spec coverage.** Every section of the spec maps to a task: nested clocks and sunrise-derived length (Tasks 1–3), the palette's three rules (Task 5), the speech layer's two doors and the intelligibility ceiling (Tasks 7–8), the steering table (Tasks 2–3, plus the bed's rain response in Task 6), blocks and the voice cache (Task 6), playback and the degradation rules (Task 9), module boundaries and the dependency direction (enforced by tests in Tasks 4 and 6), and the placeholders (Task 10).

**Three spec items are deliberately not implemented, each recorded rather than dropped:**

- **KiwiSDR as the radio transport** — replaced by an HTTP stream, flagged at the top of this plan and written into `project-state.md` by Task 10.
- **Binaural beats in the night bed** — a per-block tone restarts its phase and clicks. Noise only; recorded in Task 10.
- **Wind mapped to drift depth** — the spec's steering table maps wind to the drones' amplitude-drift depth, but drift lives in `palette.py`, which does not receive a `NightContext`. Threading one through would put steering in a second place, against the "steering enters in `clock.py` and only there" rule. Wind is therefore unmapped in Phase 1 and this is the one steering row that does nothing; it is named in Task 10's placeholder list so it is not mistaken for working.

**Placeholder scan:** no "TBD", no "similar to Task N", no step that describes without showing. The values called placeholders in Task 10 are named constants with real numbers in them, flagged as untuned rather than unwritten — which is the distinction the spec draws and the one `project-state.md` exists to carry.

**Type consistency, re-checked after writing:** `arc_at(t_s, ctx)` is called identically in `plan.py`, `stream.py` and `player.py`; `Voice.key` is composed in one place and consumed with different iteration numbers by `palette` (0) and `stream` (1), so a voice's material and its decay noise cannot collide; `render_voice(voice, sr, seed)`, `plan_voices(ctx, sr, from_frame, to_frame)`, `through_a_wall(buf, intelligibility)` and `over_the_air(buf, intelligibility, static_gain)` match between their definitions, their tests and every call site. `squelch` gained an `sr` parameter during this review — it had been smoothing with a hard-coded 44100 regardless of the rate it was handed, which would have made the gate four times slower than intended in the 22.05 kHz tests and correct only by accident at 44.1 kHz.
