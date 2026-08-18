"""CLI-level tests for the ``night`` command's user-facing seams.

The playback loop itself is covered by ``tests/test_night_player.py`` via an
injected sink and needs no device. What is not covered there is the CLI's own
wrapping: the help text (the one piece of user-facing documentation that
lives in code), and the missing-``sounddevice`` branch — the path every user
who has not installed the ``night`` extra hits on their very first run. Both
are tested here with no audio hardware and no network.
"""
from __future__ import annotations

import sys

from click.testing import CliRunner

from sleepmix.cli import main


def _no_network(monkeypatch) -> None:
    """Keep ``build_context`` off the wire.

    ``fetch_weather`` already catches every failure and falls back to
    ``NEUTRAL_WEATHER``, so this does not need to simulate anything
    elaborate — just make the one network call fail immediately rather than
    let a real request run (and possibly hang on its timeout) in a sandboxed
    test environment.
    """
    import sleepmix.night.context as ctx_mod

    def explode(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(ctx_mod, "_get_json", explode)


def test_night_help_exits_cleanly_and_documents_the_env_vars():
    result = CliRunner().invoke(main, ["night", "--help"])
    assert result.exit_code == 0
    for var in ("SLEEPMIX_LAT", "SLEEPMIX_LON", "SLEEPMIX_RADIO_URL"):
        assert var in result.output


def test_night_without_sounddevice_fails_with_an_actionable_message(
        tmp_path, monkeypatch):
    """The path every user without the ``night`` extra hits on first run.

    Setting ``sys.modules["sounddevice"] = None`` is the standard way to
    force ``import sounddevice`` to raise without the package being
    installed — it genuinely is not installed here, so this also happens to
    match reality.
    """
    _no_network(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    result = CliRunner().invoke(main, ["night"])

    assert result.exit_code != 0
    assert "sounddevice is not installed" in result.output
    assert 'pip install "sleepmix[night]"' in result.output
