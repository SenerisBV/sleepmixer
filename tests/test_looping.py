import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.looping import concat_crossfade, equal_power_crossfade, make_seamless


def test_equal_power_crossfade_invariants():
    n = 1000
    a = np.ones((n, 1), dtype=np.float32)
    b = np.zeros((n, 1), dtype=np.float32)
    out = equal_power_crossfade(a, b)
    # Endpoints honour each source exactly; the gain curve is the cos() leg.
    assert np.isclose(out[0, 0], 1.0, atol=1e-5)
    assert np.isclose(out[-1, 0], 0.0, atol=1e-5)
    # The defining property: fade_out^2 + fade_in^2 == 1 (constant power) for
    # uncorrelated sources — verify the curves sum in quadrature.
    fout = equal_power_crossfade(np.ones((n, 1), np.float32), np.zeros((n, 1), np.float32))[:, 0]
    fin = equal_power_crossfade(np.zeros((n, 1), np.float32), np.ones((n, 1), np.float32))[:, 0]
    assert np.allclose(fout ** 2 + fin ** 2, 1.0, atol=1e-5)


def test_make_seamless_shortens_by_crossfade():
    sr = 44100
    data = np.random.randn(sr, 2).astype(np.float32)
    buf = AudioBuffer(data, sr)
    out = make_seamless(buf, crossfade_ms=100)
    xfade = int(0.1 * sr)
    assert out.n_frames == buf.n_frames - xfade


def test_concat_crossfade_length():
    sr = 44100
    segs = [AudioBuffer(np.random.randn(sr, 1).astype(np.float32), sr) for _ in range(3)]
    out = concat_crossfade(segs, crossfade_ms=50)
    xfade = int(0.05 * sr)
    assert out.n_frames == 3 * sr - 2 * xfade
