"""The sky, checked against published almanac values.

Tolerances are minutes, not seconds: this is the standard low-precision
sunrise equation (no refraction model beyond the fixed -0.833 degree
correction, no topography), which is the right precision for deciding how
long a night is and the wrong precision for navigation.
"""
import datetime as dt
from pathlib import Path

import pytest

from sleepmix.night.sky import day_length_h, moon_phase, solar_events

from .import_guard import forbidden_imports

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


def test_no_shipped_module_imports_the_night_package():
    """The night subsystem must stay removable without touching the pipeline.

    Uses AST parsing to catch all import spellings, not just substrings.

    ``cli.py`` is the one deliberate exception, and only in one specific
    shape: it hosts the ``sleepmix night`` subcommand (task 9), whose whole
    purpose is to wire the night package into the CLI. But every one of its
    ``sleepmix.night`` imports lives inside the ``night()`` function body,
    never at module scope — that is this codebase's standing
    graceful-degradation pattern (the same one ``ui`` uses for ``uvicorn``),
    and it is what makes the exception safe: a function-local import only
    runs when the subcommand is invoked, so ``import sleepmix`` and
    ``sleepmix render`` keep working even with ``sleepmix/night/`` deleted,
    and only ``sleepmix night`` itself would break. A *module-scope* import
    of ``sleepmix.night`` in ``cli.py`` would not have that property — it
    would run on every ``import sleepmix.cli`` — so that spelling stays
    forbidden even for this file. The pipeline modules (render, config,
    effects, ...) get the stricter, unconditional check: no
    ``sleepmix.night`` import of any kind, anywhere in the file.
    """
    sleepmix_root = Path(__file__).parent.parent / "sleepmix"
    repo_root = sleepmix_root.parent
    forbidden = {"sleepmix.night"}
    # Only cli.py gets the relaxed, module-scope-only check; everything else
    # is swept at every scope.
    module_scope_only_for = {"cli.py"}

    # ``rglob``, not ``glob``. A top-level glob swept only ``sleepmix/*.py``
    # and left the whole of ``sleepmix/server/`` — twelve modules, including
    # the ones a hosted version would most plausibly reach into the night
    # package from — unchecked. The rule is about the package, not about the
    # top level of it.
    modules = sorted(m for m in sleepmix_root.rglob("*.py")
                     if "night" not in m.relative_to(sleepmix_root).parts)
    assert len(modules) > 20, "the sweep stopped finding modules"
    assert any(m.parent.name == "server" for m in modules), \
        "the sweep is not reaching sleepmix/server/"

    for module in modules:
        violations = forbidden_imports(
            module, repo_root, forbidden,
            module_scope_only=module.name in module_scope_only_for)
        assert not violations, (
            f"Module {module.relative_to(repo_root)} imports the night "
            f"package: {violations}, violating the package layering rule."
        )


def test_southern_hemisphere_inverts_the_season():
    """In the southern hemisphere, Dec is long and June is short (opposite of Amsterdam)."""
    sydney = (-33.8688, 151.2093)
    december = day_length_h(dt.date(2026, 12, 21), *sydney)
    june = day_length_h(dt.date(2026, 6, 21), *sydney)
    # In the southern hemisphere, December (summer) is longer than June (winter).
    assert december > june
    # Loose bounds: just verify the sign is opposite of Amsterdam.
    assert december > 14.0
    assert june < 10.0


def test_polar_midnight_sun_and_polar_night():
    """At 80N, the sun never sets in June and never rises in December."""
    arctic = (80.0, 0.0)
    # Polar night: day length near zero (within tolerance of atmosphere/refraction).
    december_length = day_length_h(dt.date(2026, 12, 21), *arctic)
    assert december_length < 1.0
    # Midnight sun: day length near 24 hours.
    june_length = day_length_h(dt.date(2026, 6, 21), *arctic)
    assert june_length > 23.0
    # solar_events must return without raising at both extremes.
    rise, set_ = solar_events(dt.date(2026, 12, 21), *arctic)
    assert isinstance(rise, dt.datetime)
    assert isinstance(set_, dt.datetime)
    rise, set_ = solar_events(dt.date(2026, 6, 21), *arctic)
    assert isinstance(rise, dt.datetime)
    assert isinstance(set_, dt.datetime)
