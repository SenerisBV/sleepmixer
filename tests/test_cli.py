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


def test_night_checks_for_a_device_before_it_says_anything_encouraging(
        tmp_path, monkeypatch):
    """A user without the extra used to read "Night 12345: 9.2 h until
    light.", "Room audio: ...", and "Ctrl-C to stop." — and *then* be told the
    thing cannot start. The check goes first, so the only thing they see is
    the one line that tells them what to install."""
    _no_network(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    output = CliRunner().invoke(main, ["night"]).output
    assert "Ctrl-C" not in output
    assert "until light" not in output
    assert "Room audio" not in output


def _fake_device(monkeypatch):
    """A ``sounddevice`` that opens without hardware and swallows writes."""
    import types

    class _Out:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, _data):
            return None

    module = types.SimpleNamespace(OutputStream=lambda **kwargs: _Out())
    monkeypatch.setitem(sys.modules, "sounddevice", module)


def _captured_run(monkeypatch) -> dict:
    """Replace the playback loop, keeping the arguments it was handed."""
    import sleepmix.night.player as player_mod

    seen: dict = {}

    def fake_run(self, max_blocks=None, sink=None):
        seen["max_blocks"] = max_blocks
        seen["night_length_s"] = self.stream.ctx.night_length_s

    monkeypatch.setattr(player_mod.NightPlayer, "run", fake_run)
    return seen


def test_a_night_with_no_seconds_is_bounded_by_the_nights_own_length(
        tmp_path, monkeypatch):
    """The spec: "Phase 1 descends toward near-silence over an assumed night
    and stops."

    What shipped stopped only for Ctrl-C — ``--seconds`` was the sole source
    of a ``max_blocks``, so ``sleepmix night`` played at noon if nobody was
    there to stop it. The night's own length is the number that says when it
    is over.
    """
    from sleepmix.night.stream import BLOCK_S

    _no_network(monkeypatch)
    _fake_device(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    seen = _captured_run(monkeypatch)

    result = CliRunner().invoke(main, ["night"])

    assert result.exit_code == 0, result.output
    assert seen["max_blocks"] is not None
    expected = int(-(-seen["night_length_s"] // BLOCK_S))  # ceil
    assert seen["max_blocks"] == expected
    # Rounded up rather than down, so the last of the descent is not clipped.
    assert seen["max_blocks"] * BLOCK_S >= seen["night_length_s"]


def test_seconds_still_overrides_the_nights_own_length(tmp_path, monkeypatch):
    _no_network(monkeypatch)
    _fake_device(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    seen = _captured_run(monkeypatch)

    result = CliRunner().invoke(main, ["night", "--seconds", "120"])

    assert result.exit_code == 0, result.output
    assert seen["max_blocks"] == 12


def test_night_says_it_is_running_on_synthesis_when_nothing_is_prepared(
        tmp_path, monkeypatch):
    """A person who has not run `prepare` should be told, not left guessing
    why it sounds the same as yesterday.

    ``_no_network`` and ``_fake_device`` are plain helper functions in this
    file, not pytest fixtures — neither carries an ``@pytest.fixture``
    decorator, and this file's other tests all call them explicitly rather
    than requesting them as arguments. The task brief wrote them as fixture
    parameters, which pytest would refuse to collect (``fixture
    '_fake_device' not found``). Called directly here, matching the existing
    convention in this file.

    Deliberately does not force the ``sounddevice`` import to fail: Phase 1
    moved that check above every ``click.echo`` on purpose, so the mode line
    below it is unreachable on that path. ``_fake_device`` exists precisely
    so the command can run far enough to print it without real hardware.
    Undoing that fix to make this test easier would be how the fix stops
    being a fix.
    """
    _no_network(monkeypatch)
    _fake_device(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(main, ["night", "--seconds", "1"])
    assert "synthesis" in result.output.lower()


def test_night_names_the_sources_it_found(tmp_path, monkeypatch):
    """See the docstring above: ``_no_network``/``_fake_device`` are called
    directly, not requested as fixtures, matching this file's convention."""
    _no_network(monkeypatch)
    _fake_device(monkeypatch)
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    from sleepmix.night.sources import SourceProfile, write_profile
    write_profile(SourceProfile(source_id="a", source_path="/a.wav",
                                loop_paths=("/a.wav",),
                                loop_frames=(1000,), pitch_set=(55.0,),
                                sr=44100))
    result = CliRunner().invoke(main, ["night", "--seconds", "1"])
    assert "1 source" in result.output
