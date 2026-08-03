import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.peaks import compute_peaks


def _buf(y, sr=22050):
    arr = np.asarray(y, dtype=np.float32)
    return AudioBuffer(np.stack([arr, arr], axis=1), sr)


def test_returns_one_min_max_pair_per_bucket():
    peaks = compute_peaks(_buf(np.sin(np.linspace(0, 100, 10000))), buckets=50)
    assert len(peaks) == 50
    assert all(len(p) == 2 for p in peaks)
    assert all(p[0] <= p[1] for p in peaks)


def test_tracks_a_rising_envelope():
    """A ramp must produce buckets whose maxima increase."""
    ramp = np.linspace(0.0, 1.0, 10000)
    peaks = compute_peaks(_buf(ramp), buckets=10)
    maxima = [p[1] for p in peaks]
    assert maxima == sorted(maxima)
    assert maxima[-1] > maxima[0]


def test_captures_sign_of_the_signal():
    y = np.concatenate([np.full(5000, -0.5), np.full(5000, 0.5)])
    peaks = compute_peaks(_buf(y), buckets=2)
    assert peaks[0][0] < 0 and peaks[0][1] < 0.01
    assert peaks[1][1] > 0


def test_short_buffer_does_not_produce_empty_buckets():
    """Fewer frames than buckets must still yield well-formed pairs."""
    peaks = compute_peaks(_buf(np.linspace(-1, 1, 7)), buckets=100)
    assert len(peaks) == 100
    assert all(np.isfinite(p).all() for p in peaks)


def test_empty_buffer_returns_zeroed_pairs():
    peaks = compute_peaks(AudioBuffer(np.zeros((0, 2), dtype=np.float32), 44100), buckets=8)
    assert peaks == [[0.0, 0.0]] * 8


def test_values_are_json_serializable_floats():
    import json

    peaks = compute_peaks(_buf(np.sin(np.linspace(0, 10, 1000))), buckets=16)
    json.dumps(peaks)  # must not raise on numpy scalars
    assert isinstance(peaks[0][0], float)
