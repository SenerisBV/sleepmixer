import numpy as np
import pytest
from scipy.signal import welch

from sleepmix.esoterica.character import KINDS, apply_character

SR = 44100


def speechy(seconds=3.0, seed=0):
    """Harmonics of a gliding ~140 Hz voice up to 3 kHz with a syllable envelope.
    The glide spreads each harmonic over a band like real speech (a fixed line
    would land on one random bin of a reverb's fine-grained response)."""
    t = np.arange(int(seconds * SR)) / SR
    phase = 2 * np.pi * np.cumsum(140 + 35 * np.sin(2 * np.pi * 3.3 * t)) / SR
    x = sum(np.sin(k * phase + k) / k for k in range(1, 22))
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


def test_oldmic_band_shape_on_white_noise():
    x = (np.random.default_rng(1).standard_normal(SR * 4) * 0.1).astype(np.float32)
    y = apply_character(x, SR, "oldmic", 1)
    f, p = welch(y, SR, nperseg=8192)
    assert p[f < 120].sum() / p.sum() < 0.02
    assert p[f > 6000].sum() / p.sum() < 0.15
    assert p[(f > 300) & (f < 3000)].sum() / p.sum() > 0.5


def test_room_tail_decays_to_minus_60_db_within_half_a_second():
    imp = np.zeros(SR * 2, np.float32)
    imp[100] = 1.0
    wet = apply_character(imp, SR, "room", 1).astype(np.float64) - imp
    e = np.cumsum((wet ** 2)[::-1])[::-1]
    e = 10 * np.log10(e / e[0] + 1e-30)
    t60 = (np.argmax(e < -60) - 100) / SR
    assert 0.2 <= t60 <= 0.5, t60


def test_room_is_about_fifteen_percent_wet_in_the_voice_band():
    from scipy.signal import butter, sosfilt
    x = (np.random.default_rng(2).standard_normal(SR * 6) * 0.1)
    x = sosfilt(butter(4, [100, 4000], "band", fs=SR, output="sos"), x).astype(np.float32)
    y = apply_character(x, SR, "room", 1)
    wet = np.sum((y.astype(np.float64) - x) ** 2)
    share = wet / (wet + np.sum(x.astype(np.float64) ** 2))
    assert 0.11 <= share <= 0.17, share


def test_room_level_stays_near_input_without_rms_matching():
    # one reverb tail response is random per bin, so a held tonal voice moves a
    # little by seed; the mean is the ~15% wet expectation (+0.6 dB)
    x = speechy()
    d = [rms_db(apply_character(x, SR, "room", s)) - rms_db(x) for s in range(10)]
    assert abs(np.mean(d)) <= 1.0 and max(abs(v) for v in d) <= 2.5


def test_hum_has_no_step_at_sample_zero():
    y = apply_character(np.zeros(SR, np.float32), SR, "hum", 5)
    assert abs(y[0]) < 1e-9 and np.abs(np.diff(y)).max() < 10 ** (-55 / 20) * 0.1


def test_character_params_name_the_recipe_constants():
    from sleepmix.esoterica import character
    from sleepmix.esoterica.character import character_params
    p = character_params("tape")
    assert p["kind"] == "tape"
    assert p["TAPE_HISS_DB"] == character.TAPE_HISS_DB
    assert p["TAPE_LOWPASS_HZ"] == character.TAPE_LOWPASS_HZ
    assert not any(k.startswith("ROOM_") for k in p)
    assert character_params("room")["ROOM_VOICE_BAND_HZ"] == list(character.ROOM_VOICE_BAND_HZ)
    assert character_params("clean") == {"kind": "clean"}
    with pytest.raises(ValueError):
        character_params("vinyl")
