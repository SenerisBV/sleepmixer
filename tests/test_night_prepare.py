"""The expensive half, and the promise that it never runs at bedtime.

Demucs on a laptop spins the fans for minutes, next to the bed. Everything
here exists so that `sleepmix night` can be instant and silent about it, and
the last test in this file is the one that keeps that true.
"""
import os
import time

import numpy as np
import pytest
import soundfile as sf

from sleepmix.night import prepare as prepare_mod
from sleepmix.night.prepare import (
    LOOPS_PER_SOURCE, prepare_all, prepare_source, source_id_for,
)
from sleepmix.night.sources import load_profiles, sources_directory

SR = 22050


def _write_song(path, seconds=30.0, sr=SR, freqs=(110.0, 164.81)):
    t = np.arange(int(seconds * sr)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    y = (y / np.abs(y).max() * 0.5).astype(np.float32)
    sf.write(str(path), np.stack([y, y], axis=1), sr)
    return str(path)


@pytest.fixture(autouse=True)
def _stub_separation(monkeypatch):
    """Demucs is not installed here and must never be needed by a test."""
    from sleepmix.audio import load_audio

    def fake_separate(input_path, model="htdemucs_ft", cache_dir=None):
        src = load_audio(str(input_path))
        return {"other": src, "drums": src}

    monkeypatch.setattr(prepare_mod, "separate", fake_separate)


def test_a_source_id_is_stable_for_a_path():
    assert source_id_for("/a/b/Song.wav") == source_id_for("/a/b/Song.wav")


def test_a_source_id_differs_between_paths():
    assert source_id_for("/a/one.wav") != source_id_for("/a/two.wav")


def test_a_source_id_is_filesystem_safe():
    ident = source_id_for("/a/b/Weird Name (mix) #2.wav")
    assert ident and all(c.isalnum() or c in "-_" for c in ident)


def test_preparing_a_song_produces_loops_and_pitches(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav")
    profile = prepare_source(song, sr=SR)
    assert profile is not None
    assert len(profile.loop_paths) == LOOPS_PER_SOURCE
    assert len(profile.loop_frames) == LOOPS_PER_SOURCE
    assert profile.pitch_set
    assert profile.sr == SR


def test_the_loop_files_actually_exist_and_match_their_frame_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for path, frames in zip(profile.loop_paths, profile.loop_frames):
        assert os.path.exists(path)
        info = sf.info(path)
        assert info.frames == frames


def test_the_loops_are_short_enough_to_carry_no_phrase(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    profile = prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    for frames in profile.loop_frames:
        assert 1.0 <= frames / profile.sr <= 40.0


def test_dropped_stems_do_not_reach_the_loops(tmp_path, monkeypatch):
    """Drums looping under you at 2 AM is what the render defaults already
    turn off by hand."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    seen = {}

    real = prepare_mod._kept_stems

    def spy(stems):
        kept = real(stems)
        seen["names"] = sorted(kept)
        return kept

    monkeypatch.setattr(prepare_mod, "_kept_stems", spy)
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    assert "drums" not in seen["names"]
    assert "other" in seen["names"]


def test_preparing_writes_a_profile_that_loads_back(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    prepare_source(_write_song(tmp_path / "song.wav"), sr=SR)
    loaded = load_profiles()
    assert len(loaded) == 1
    assert loaded[0].pitch_set


def test_prepare_all_walks_the_sources_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    _write_song(os.path.join(sources_directory(), "two.wav"), freqs=(146.83,))
    assert len(prepare_all()) == 2
    assert len(load_profiles()) == 2


def test_prepare_all_on_an_empty_folder_is_an_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    assert prepare_all() == ()


def test_prepare_all_is_idempotent(tmp_path, monkeypatch):
    """Re-running costs nothing for an unchanged source."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    first = prepare_all()
    calls = {"n": 0}
    real = prepare_mod.prepare_source

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prepare_mod, "prepare_source", counted)
    second = prepare_all()
    assert calls["n"] == 0
    assert [p.source_id for p in first] == [p.source_id for p in second]


def test_a_file_that_will_not_decode_costs_one_source_not_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "good.wav"))
    with open(os.path.join(sources_directory(), "bad.wav"), "w") as fh:
        fh.write("not audio")
    assert len(prepare_all()) == 1


def test_prepare_reports_progress_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    _write_song(os.path.join(sources_directory(), "one.wav"))
    lines = []
    prepare_all(progress=lines.append)
    assert lines


def test_prepare_source_resamples_to_the_requested_rate(tmp_path, monkeypatch):
    """``sr`` is the promised output rate, not a value that only happens to
    match if the source file was already at it. A source recorded at some
    other rate must still come out (and be saved) at the one requested."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav", sr=8000)
    profile = prepare_source(song, sr=22050)
    assert profile is not None
    assert profile.sr == 22050
    for path in profile.loop_paths:
        assert sf.info(path).samplerate == 22050


def test_a_bad_source_id_from_write_profile_is_not_swallowed(tmp_path, monkeypatch):
    """``write_profile`` raises ``ValueError`` for an unsafe id on purpose —
    that is a programming error, not an ordinary per-file condition, and
    ``prepare_source``'s broad ``except Exception`` must not turn it back
    into a quiet ``None``."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    song = _write_song(tmp_path / "song.wav")

    def bad_write_profile(profile):
        raise ValueError("unsafe source_id: '..'")

    monkeypatch.setattr(prepare_mod, "write_profile", bad_write_profile)
    with pytest.raises(ValueError):
        prepare_source(song, sr=SR)


def test_editing_a_source_in_place_causes_reprocessing(tmp_path, monkeypatch):
    """Same path, new content: prepare_all must not read a stale profile as
    'already prepared' forever."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    path = os.path.join(sources_directory(), "one.wav")
    _write_song(path, freqs=(110.0,))
    prepare_all()

    _write_song(path, freqs=(146.83, 220.0))
    future = time.time() + 5
    os.utime(path, (future, future))

    calls = {"n": 0}
    real = prepare_mod.prepare_source

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(prepare_mod, "prepare_source", counted)
    prepare_all()
    assert calls["n"] == 1


def test_loops_per_source_beyond_search_windows_fails_loudly(tmp_path, monkeypatch):
    """A drift between LOOPS_PER_SOURCE and _SEARCH_WINDOWS is a programming
    error; it must not silently hand back fewer loops than promised."""
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(prepare_mod, "LOOPS_PER_SOURCE", 99)
    song = _write_song(tmp_path / "song.wav")
    with pytest.raises(RuntimeError):
        prepare_source(song, sr=SR)


def test_the_night_module_never_imports_prepare():
    """The promise that bedtime is silent: nothing on the playback path may
    reach the module that runs Demucs."""
    import pathlib
    from .import_guard import forbidden_imports
    root = pathlib.Path(__file__).resolve().parent.parent
    forbidden = {"sleepmix.night.prepare", "sleepmix.separation",
                 "sleepmix.separation_process", "sleepmix.analysis",
                 "sleepmix.timestretch"}
    for name in ("plan.py", "palette.py", "stream.py", "player.py",
                 "clock.py", "context.py", "sources.py"):
        offenders = forbidden_imports(
            root / "sleepmix" / "night" / name, root, forbidden)
        assert offenders == set(), f"{name} reaches preparation: {offenders}"
