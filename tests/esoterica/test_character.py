import numpy as np
import pytest
from scipy.signal import welch

from sleepmix.esoterica.character import KINDS, apply_character

SR = 44100


def speechy(seconds=3.0, seed=0):
    """Harmonics of 140 Hz up to 3 kHz with a slow syllable envelope."""
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * 140 * k * t + k) / k for k in range(1, 22))
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (0.1 * x * env / np.abs(x).max() * 3).astype(np.float32)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def max_jump(x):
    return float(np.max(np.abs(np.diff(x))))


def test_kinds():
    assert set(KINDS) == {"tape", "room", "oldmic", "hum", "clean"}


def test_clean_is_identity():
    x = speechy()
    y = apply_character(x, SR, "clean", 1)
    assert y.dtype == np.float32
    np.testing.assert_array_equal(y, x)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        apply_character(speechy(), SR, "vinyl", 1)


@pytest.mark.parametrize("kind", ["tape", "room", "oldmic", "hum"])
def test_recipe_is_subtle_clickless_and_deterministic(kind):
    x = speechy()
    y = apply_character(x, SR, kind, 7)
    assert y.shape == x.shape and y.dtype == np.float32
    assert abs(rms_db(y) - rms_db(x)) <= 1.5
    assert max_jump(y) <= 1.5 * max_jump(x)
    assert not np.array_equal(y, x)
    np.testing.assert_array_equal(y, apply_character(x, SR, kind, 7))


def test_seed_changes_tape_hiss():
    x = speechy()
    assert not np.array_equal(apply_character(x, SR, "tape", 1),
                              apply_character(x, SR, "tape", 2))


def test_oldmic_cuts_low_end_on_white_noise():
    x = (np.random.default_rng(0).standard_normal(SR * 4) * 0.1).astype(np.float32)
    y = apply_character(x, SR, "oldmic", 1)
    f, p = welch(y, SR, nperseg=8192)
    assert p[f < 120].sum() / p.sum() < 0.02


def test_hum_adds_a_50hz_peak():
    x = np.zeros(SR * 4, np.float32)
    y = apply_character(x, SR, "hum", 1)
    f, p = welch(y, SR, nperseg=SR * 4, window="boxcar")
    i50 = np.argmin(abs(f - 50))
    assert p[i50] > 100 * np.median(p[(f > 60) & (f < 90)] + 1e-30)
    assert 10 ** (-60 / 20) < np.abs(y).max() < 10 ** (-45 / 20)


def test_tape_adds_hiss_floor():
    y = apply_character(np.zeros(SR * 2, np.float32), SR, "tape", 3)
    assert -56 < rms_db(y) < -48
