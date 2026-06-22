import numpy as np

from sleepmix.config import SoundbedConfig
from sleepmix.soundbed import binaural_beat, build_soundbed, colored_noise


def test_colored_noise_length_and_finite():
    rng = np.random.default_rng(0)
    y = colored_noise(44100, 44100, "pink", rng)
    assert y.shape == (44100,)
    assert np.all(np.isfinite(y))


def test_pink_has_more_low_energy_than_white():
    rng = np.random.default_rng(1)
    n = 44100
    pink = colored_noise(n, n, "pink", rng)
    white = colored_noise(n, n, "white", rng)

    def low_high_ratio(x):
        spec = np.abs(np.fft.rfft(x))
        half = len(spec) // 2
        return spec[:half].mean() / (spec[half:].mean() + 1e-9)

    # Pink tilts energy toward low frequencies; white is ~flat (ratio ≈ 1).
    assert low_high_ratio(pink) > 1.8
    assert low_high_ratio(white) < 1.4
    assert low_high_ratio(pink) > low_high_ratio(white) * 1.8


def test_binaural_channels_differ():
    tone = binaural_beat(44100, 44100, 110.0, 4.0)
    assert tone.shape == (44100, 2)
    # Left and right carriers differ by the beat frequency, so channels diverge.
    assert not np.allclose(tone[:, 0], tone[:, 1])


def test_build_soundbed_stereo_duration():
    cfg = SoundbedConfig(enabled=True, binaural_enabled=True)
    rng = np.random.default_rng(0)
    bed = build_soundbed(2.0, 22050, cfg, rng)
    assert bed.n_channels == 2
    assert abs(bed.duration - 2.0) < 0.01
