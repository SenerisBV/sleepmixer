"""What the planner is allowed to know about a song.

Everything here is a path, a count or a number. No audio, ever — that is what
lets `night/plan.py` import this module without breaking the guard that keeps
an eight-hour night plannable in microseconds.
"""
import json
import math
import os

import pytest

from sleepmix.night import sources as sources_mod
from sleepmix.night.sources import (
    PROFILE_SUFFIX, SourceProfile, _MAX_DISTANCE_CENTS, load_profiles,
    pitch_distance, profiles_directory, sources_directory, write_profile,
)


def _profile(source_id="a", pitches=(55.0, 82.5), loops=("/tmp/x.wav",),
             frames=(220500,), sr=44100):
    return SourceProfile(source_id=source_id, loop_paths=tuple(loops),
                         loop_frames=tuple(frames), pitch_set=tuple(pitches),
                         sr=sr)


def test_sources_module_imports_no_audio():
    from .import_guard import forbidden_imports
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = forbidden_imports(
        root / "sleepmix" / "night" / "sources.py", root,
        {"numpy", "scipy", "soundfile", "pedalboard", "sleepmix.audio",
         "sleepmix.effects", "sleepmix.night.pitch", "sleepmix.night.prepare",
         "sleepmix.night.palette", "sleepmix.night.stream"})
    assert offenders == set(), f"sources.py imports audio: {offenders}"


def test_a_profile_round_trips_through_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    written = write_profile(_profile())
    assert written.endswith(PROFILE_SUFFIX)
    assert load_profiles() == (_profile(),)


def test_profiles_come_back_in_a_stable_order(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    for name in ("c", "a", "b"):
        write_profile(_profile(source_id=name))
    assert [p.source_id for p in load_profiles()] == ["a", "b", "c"]


def test_no_profiles_directory_is_an_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "nothing-here"))
    assert load_profiles() == ()


def test_a_corrupt_profile_is_skipped_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    bad = os.path.join(profiles_directory(), "bad" + PROFILE_SUFFIX)
    with open(bad, "w") as fh:
        fh.write("{ this is not json")
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_missing_a_key_is_skipped_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    partial = os.path.join(profiles_directory(), "partial" + PROFILE_SUFFIX)
    with open(partial, "w") as fh:
        json.dump({"source_id": "partial"}, fh)
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_with_no_loops_is_skipped(tmp_path, monkeypatch):
    """A profile that names no material cannot produce a voice."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    write_profile(_profile(source_id="empty", loops=(), frames=()))
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_a_profile_whose_loops_and_frames_disagree_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    write_profile(_profile(source_id="ragged", loops=("/a.wav", "/b.wav"),
                           frames=(100,)))
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_the_directories_live_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert str(tmp_path) in sources_directory()
    assert sources_directory().endswith("sources")
    assert str(tmp_path) in profiles_directory()


def test_pitch_distance_is_zero_for_identical_sets():
    assert pitch_distance(_profile(), _profile()) == pytest.approx(0.0)


def test_pitch_distance_grows_with_disagreement():
    near = pitch_distance(_profile(pitches=(55.0, 82.5)),
                          _profile(pitches=(56.0, 83.0)))
    far = pitch_distance(_profile(pitches=(55.0, 82.5)),
                         _profile(pitches=(75.0, 104.0)))
    assert 0.0 < near < far


def test_pitch_distance_survives_an_empty_set():
    d = pitch_distance(_profile(pitches=()), _profile())
    assert d >= 0.0 and not math.isnan(d)


def test_pitch_distance_survives_a_zero_or_negative_pitch():
    """Regression: ``math.log2(hz / other)`` is undefined at hz <= 0.

    ``_read_profile`` validates ``loop_frames`` and ``sr`` but nothing stops
    an older or hand-edited profile from naming a zero or negative pitch.
    Before this was filtered, ``pitch_distance`` raised ``ValueError``
    (a "positive input" domain error) instead of degrading, which is exactly
    the kind of failure this module exists to turn into a skip.
    """
    d = pitch_distance(_profile(pitches=(0.0, -55.0)), _profile())
    assert d == pytest.approx(_MAX_DISTANCE_CENTS)

    # A mix of valid and invalid pitches: the invalid ones are dropped, not
    # allowed to poison the whole comparison.
    mixed = pitch_distance(_profile(pitches=(0.0, 55.0, 82.5)),
                           _profile(pitches=(55.0, 82.5)))
    assert mixed == pytest.approx(0.0)


def test_a_profile_with_a_non_positive_sample_rate_is_skipped(tmp_path, monkeypatch):
    """Regression: everything downstream turns frames into seconds via ``sr``."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="good"))
    write_profile(_profile(source_id="zero_sr", sr=0))
    write_profile(_profile(source_id="negative_sr", sr=-44100))
    assert [p.source_id for p in load_profiles()] == ["good"]


def test_load_profiles_does_not_call_profiles_directory_again_per_file(
        tmp_path, monkeypatch):
    """Regression: the brief's ``load_profiles`` called ``profiles_directory()``
    a second time, unprotected, inside the per-file loop. That function also
    calls ``os.makedirs``, which can raise for reasons unrelated to any one
    profile (the directory removed and re-creation blocked, replaced by a
    non-directory, permissions revoked between files) — and this function is
    documented as never raising. Reproduced by letting exactly one call
    through and failing every call after: against the buggy code this raises
    while reading the very first file; against the fix, the directory is
    resolved once and reused, so both profiles are still found.
    """
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    write_profile(_profile(source_id="a"))
    write_profile(_profile(source_id="b"))

    real = sources_mod.profiles_directory
    calls = {"n": 0}

    def once_then_fail():
        calls["n"] += 1
        if calls["n"] > 1:
            raise PermissionError("directory vanished")
        return real()

    monkeypatch.setattr(sources_mod, "profiles_directory", once_then_fail)
    assert [p.source_id for p in load_profiles()] == ["a", "b"]
    assert calls["n"] == 1


def test_load_profiles_never_raises_even_if_the_directory_is_unusable(monkeypatch):
    """``load_profiles`` is documented never to raise -- including when
    resolving the profiles directory itself is what fails."""
    def _raise():
        raise PermissionError("nope")

    monkeypatch.setattr(sources_mod, "profiles_directory", _raise)
    assert load_profiles() == ()


def test_write_profile_rejects_an_unsafe_source_id(tmp_path, monkeypatch):
    """``write_profile`` validates its own caller's input and raises rather
    than skips: an id that could escape ``profiles_directory()`` is a
    programming error, not an ordinary fact about the world to route around.
    """
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    for bad_id in ("", ".", "..", "a/b", "../escape", "/etc/passwd"):
        with pytest.raises(ValueError):
            write_profile(_profile(source_id=bad_id))


def test_write_profile_sweeps_a_stale_partial_for_the_same_id(tmp_path, monkeypatch):
    """A killed writer can leave a ``.partial`` behind. The next write for
    that same ``source_id`` should not be confused by it, and none should
    remain once the write completes -- mirroring ``separation._write_cache``,
    which is what this module's docstring claims parity with.
    """
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    stale = os.path.join(profiles_directory(), "a" + PROFILE_SUFFIX + ".partial")
    with open(stale, "w") as fh:
        fh.write("leftover from a killed prepare")

    write_profile(_profile(source_id="a"))

    assert not os.path.exists(stale)
    assert [p.source_id for p in load_profiles()] == ["a"]


def test_a_profile_is_frozen():
    with pytest.raises(Exception):
        _profile().source_id = "other"  # type: ignore[misc]
