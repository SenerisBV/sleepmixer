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
