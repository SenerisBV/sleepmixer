import numpy as np

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

    Otherwise the second load looks like a successful separation and the UI
    stops explaining why there is only one stem."""
    import sleepmix.separation as sep

    song = tmp_path / "s.wav"
    _song(song)
    cache = str(tmp_path / "cache")
    monkeypatch.setattr(sep, "_demucs_separate",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no torch")))

    first = separate_detailed(str(song), cache_dir=cache)
    second = separate_detailed(str(song), cache_dir=cache)
    assert first.fallback_reason is not None
    assert second.fallback_reason == first.fallback_reason


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
