import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.separation import SeparationResult, separate, separate_detailed


def _song(path, sr=22050, secs=2.0):
    t = np.arange(int(sr * secs)) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    save_audio(AudioBuffer(np.stack([y, y], axis=1), sr), str(path))


def test_fallback_reports_a_reason(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))

    result = separate_detailed(str(song), cache_dir=str(tmp_path / "cache"))
    assert isinstance(result, SeparationResult)
    assert set(result.stems) == {"mix"}
    assert result.fallback_reason is not None
    assert "no torch" in result.fallback_reason


def test_fallback_reason_survives_a_cache_hit(tmp_path, monkeypatch):
    """A cached fallback must still report itself as a fallback.

    Counts separation calls so the test proves the second read came from the
    cache — comparing two identical reason strings would pass even if nothing
    were cached at all."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    calls = []

    def failing(input_path, model):
        calls.append(1)
        raise RuntimeError("no torch")

    monkeypatch.setattr(sep, "_demucs_separate", failing)

    first = separate_detailed(str(song), cache_dir=cache)
    second = separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 1, "second call should have hit the cache"
    assert first.fallback_reason is not None
    assert second.fallback_reason == first.fallback_reason


def test_a_marker_without_stems_does_not_masquerade_as_success(tmp_path, monkeypatch):
    """The marker/stem write window must fail safe.

    If the marker lands but the stems do not, the next call must redo the
    separation rather than trusting a cache directory that holds only a
    marker."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    calls = []

    def failing(input_path, model):
        calls.append(1)
        raise RuntimeError("no torch")

    monkeypatch.setattr(sep, "_demucs_separate", failing)

    real_save_cache = sep._save_cache

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(sep, "_save_cache", boom)
    with pytest.raises(OSError):
        separate_detailed(str(song), cache_dir=cache)

    monkeypatch.setattr(sep, "_save_cache", real_save_cache)
    result = separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 2, "the second call must have re-run separation"
    assert result.fallback_reason is not None


def test_successful_separation_has_no_reason(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    song = tmp_path / "s.wav"
    _song(song)

    def fake(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", fake)
    result = separate_detailed(str(song), cache_dir=str(tmp_path / "cache"))
    assert result.fallback_reason is None
    assert set(result.stems) == {"vocals", "drums", "bass", "other"}


def test_separate_keeps_its_dict_contract(tmp_path, monkeypatch):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("nope")))

    stems = separate(str(song), cache_dir=str(tmp_path / "cache"))
    assert isinstance(stems, dict)
    assert set(stems) == {"mix"}


def test_invalidate_cache_forces_a_recompute(tmp_path, monkeypatch):
    """Without this, a cached fallback is permanent — the cache key does not
    include whether Demucs was available, so installing it later changes
    nothing."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    calls = []

    def failing(input_path, model):
        calls.append(1)
        raise RuntimeError("no torch")

    monkeypatch.setattr(sep, "_demucs_separate", failing)
    separate_detailed(str(song), cache_dir=cache)
    separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 1

    assert sep.invalidate_cache(str(song), cache_dir=cache) is True
    separate_detailed(str(song), cache_dir=cache)
    assert len(calls) == 2


def test_invalidate_cache_is_false_when_nothing_was_cached(tmp_path):
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    assert sep.invalidate_cache(str(song), cache_dir=str(tmp_path / "cache")) is False


def test_a_successful_rerun_clears_the_stale_marker(tmp_path, monkeypatch):
    """The whole point of invalidation: a fallback must stop being reported
    once the real thing works."""
    import sleepmix.separation as sep

    from sleepmix.audio import load_audio

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")

    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))
    assert separate_detailed(str(song), cache_dir=cache).fallback_reason is not None

    def working(input_path, model):
        src = load_audio(input_path)
        return {name: AudioBuffer(src.data.copy(), src.sr)
                for name in ("vocals", "drums", "bass", "other")}

    monkeypatch.setattr(sep, "_demucs_separate", working)
    sep.invalidate_cache(str(song), cache_dir=cache)
    result = separate_detailed(str(song), cache_dir=cache)
    assert result.fallback_reason is None
    assert set(result.stems) == {"vocals", "drums", "bass", "other"}
