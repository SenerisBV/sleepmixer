"""End-to-end render through the fallbacks (no ML deps required)."""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer, load_audio, save_audio
from sleepmix.config import MixConfig
from sleepmix.pipeline import run_pipeline
from sleepmix.progress import CancelToken, Cancelled, ProgressReporter


def _synth_song(path, sr=22050, secs=6.0):
    """A simple chord + melody so there's something to loop and separate."""
    t = np.arange(int(sr * secs)) / sr
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330))
    melody = 0.5 * np.sin(2 * np.pi * (440 + 40 * np.sin(2 * np.pi * 0.5 * t)) * t)
    y = (chord + melody) / 4.0
    stereo = np.stack([y, y], axis=1).astype(np.float32)
    save_audio(AudioBuffer(stereo, sr), str(path))


def test_full_render_fallback(tmp_path):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.25      # 15 s render to keep the test fast
    cfg.output.sample_rate = 22050
    cfg.soundbed.enabled = True
    cfg.soundbed.binaural_enabled = True

    run_pipeline(str(song), cfg, str(out), progress=lambda *_: None)

    rendered = load_audio(str(out))
    assert rendered.n_channels == 2
    assert abs(rendered.duration - 15.0) < 1.0
    assert np.all(np.isfinite(rendered.data))
    # Mastered peak should respect the configured ceiling (-1 dBFS).
    assert np.max(np.abs(rendered.data)) <= 10 ** (-1.0 / 20.0) + 1e-3


def test_reporter_receives_ordered_monotonic_events(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    seen = []
    run_pipeline(str(song), cfg, str(out), reporter=ProgressReporter(seen.append))

    stages = [e.stage for e in seen]
    assert stages[0] == "separate"
    assert stages[-1] == "master"
    assert "stem" in stages
    fractions = [e.fraction for e in seen]
    assert fractions == sorted(fractions), "progress must never go backwards"
    assert 0.0 <= fractions[0] and fractions[-1] <= 1.0


def test_cancel_aborts_the_render(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    token = CancelToken()
    # Cancel as soon as the first event arrives.
    reporter = ProgressReporter(lambda _e: token.cancel())

    with pytest.raises(Cancelled):
        run_pipeline(str(song), cfg, str(out), reporter=reporter, cancel=token)

    assert not out.exists(), "a cancelled render must not leave output behind"


def test_string_progress_callback_still_works(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    lines = []
    run_pipeline(str(song), cfg, str(out), progress=lines.append)

    assert any("Separating" in line for line in lines)
    assert any("Wrote" in line for line in lines)
