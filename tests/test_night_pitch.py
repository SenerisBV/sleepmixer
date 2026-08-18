"""What is actually in the material, as numbers.

The ghost's drones sound at frequencies physically present in the source, not
at the notes of a key some estimator inferred from it. That is the whole
difference between this and chroma detection, and it is why these tests
synthesize known partials and demand them back rather than asserting anything
musicological.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night.pitch import (
    FOLD_HIGH_HZ, FOLD_LOW_HZ, MIN_PEAK_FRACTION, _fold, pitch_set,
)

SR = 22050


def _tone(freqs, seconds=2.0, sr=SR, amps=None):
    t = np.arange(int(seconds * sr)) / sr
    amps = amps or [1.0] * len(freqs)
    y = sum(a * np.sin(2 * np.pi * f * t) for f, a in zip(freqs, amps))
    y = (y / max(np.abs(y).max(), 1e-9) * 0.5).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def _folded(hz):
    """Where a frequency should land after octave folding."""
    while hz >= FOLD_HIGH_HZ:
        hz /= 2.0
    while hz < FOLD_LOW_HZ:
        hz *= 2.0
    return hz


def test_a_single_tone_gives_one_pitch():
    found = pitch_set(_tone([220.0]))
    assert len(found) == 1
    assert found[0] == pytest.approx(_folded(220.0), abs=1.5)


def test_three_tones_give_three_pitches():
    # 220.0 is deliberately not used here: it is the exact octave of 110.0,
    # so it would fold onto the same pitch class and the count would be 2,
    # not 3. That case belongs to test_octaves_fold_onto_each_other below.
    found = pitch_set(_tone([110.0, 164.81, 196.0]))
    assert len(found) == 3


def test_octaves_fold_onto_each_other():
    """A tone and its octave are the same pitch class and must not be two."""
    found = pitch_set(_tone([110.0, 220.0, 440.0]))
    assert len(found) == 1
    # 110.0 itself folds to 55.0: the band is [FOLD_LOW_HZ, FOLD_HIGH_HZ),
    # so FOLD_HIGH_HZ (110.0) is one octave above the band, not inside it —
    # see test_every_pitch_lands_inside_the_fold_band below.
    assert found[0] == pytest.approx(_folded(110.0), abs=1.5)


def test_every_pitch_lands_inside_the_fold_band():
    found = pitch_set(_tone([55.0, 233.08, 880.0, 1760.0]))
    assert found
    for hz in found:
        assert FOLD_LOW_HZ <= hz < FOLD_HIGH_HZ


def test_the_set_is_ascending_and_has_no_duplicates():
    found = pitch_set(_tone([146.83, 220.0, 110.0, 329.63]))
    assert list(found) == sorted(found)
    assert len(set(found)) == len(found)


def test_max_pitches_is_honoured():
    eight_tones = [110.0, 123.47, 130.81, 146.83, 164.81, 174.61, 196.0, 207.65]
    found = pitch_set(_tone(eight_tones), max_pitches=3)
    assert len(found) <= 3


def test_max_pitches_zero_gives_no_pitches():
    """The bound is checked before a pitch is kept, not after."""
    found = pitch_set(_tone([110.0, 164.81, 220.0]), max_pitches=0)
    assert found == ()


def test_max_pitches_one_gives_at_most_one_pitch():
    found = pitch_set(_tone([110.0, 164.81, 220.0]), max_pitches=1)
    assert len(found) <= 1


def test_a_quiet_partial_below_the_threshold_is_ignored():
    loud_only = pitch_set(_tone([110.0, 164.81], amps=[1.0, 0.001]))
    assert len(loud_only) == 1


def test_silence_gives_an_empty_set_rather_than_raising():
    quiet = AudioBuffer(np.zeros((SR, 2), dtype=np.float32), SR)
    assert pitch_set(quiet) == ()


def test_an_empty_buffer_gives_an_empty_set_rather_than_raising():
    empty = AudioBuffer(np.zeros((0, 2), dtype=np.float32), SR)
    assert pitch_set(empty) == ()


def test_a_mono_buffer_is_accepted():
    t = np.arange(SR) / SR
    y = (0.5 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    assert len(pitch_set(AudioBuffer(y, SR))) == 1


def test_the_result_is_reproducible():
    buf = _tone([110.0, 164.81])
    assert pitch_set(buf) == pitch_set(buf)


def test_the_threshold_constant_is_a_fraction():
    assert 0.0 < MIN_PEAK_FRACTION < 1.0


def test_fold_does_not_hang_on_non_finite_input():
    """A positive infinity halves forever under naive octave folding.

    ``_fold`` should never receive one from ``pitch_set`` in practice — every
    bin ``rfftfreq`` produces is finite — but the function is a public seam
    within the module and pathological input to it should degrade, not hang
    the process.
    """
    assert _fold(float("inf")) == 0.0
    assert _fold(float("-inf")) == 0.0
    assert _fold(float("nan")) == 0.0
