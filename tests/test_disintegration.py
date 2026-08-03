import numpy as np

from sleepmix.audio import AudioBuffer
from sleepmix.config import StemDecayConfig
from sleepmix.disintegration import (
    apply_decay, build_disintegrating_stream, decayed_iteration, plan_iterations)
from sleepmix.util import iteration_rng


def _tone(freq, sr=22050, secs=1.0):
    t = np.arange(int(sr * secs)) / sr
    return AudioBuffer(np.sin(2 * np.pi * freq * t)[:, None].astype(np.float32), sr)


def _band_peak(buf, sr, lo, hi):
    """Peak spectral magnitude in [lo, hi) — isolates a tone from filter skirt."""
    spec = np.abs(np.fft.rfft(buf.data[:, 0]))
    freqs = np.fft.rfftfreq(buf.n_frames, 1.0 / sr)
    return spec[(freqs > lo) & (freqs < hi)].max()


def test_decay_attenuates_high_frequencies():
    sr = 22050
    # Sum of a low and a high tone; decay should erode the high one.
    low = _tone(300, sr).data
    high = _tone(8000, sr).data
    buf = AudioBuffer(low + high, sr)
    rng = np.random.default_rng(0)
    decay = StemDecayConfig(lowpass_end_hz=1500, spectral_hole_end=0,
                            dropout_end=0, noise_end_db=-120, amp_end_db=0)
    out = apply_decay(buf, progress=1.0, decay=decay, rng=rng)
    # The 8 kHz tone should be all but gone after a lowpass to 1.5 kHz…
    assert _band_peak(out, sr, 7000, 9000) < _band_peak(buf, sr, 7000, 9000) * 0.01
    # …while the 300 Hz tone (below the cutoff) survives.
    assert _band_peak(out, sr, 200, 400) > _band_peak(buf, sr, 200, 400) * 0.5


def test_zero_progress_is_passthrough():
    buf = _tone(440)
    rng = np.random.default_rng(0)
    out = apply_decay(buf, progress=0.0, decay=StemDecayConfig(), rng=rng)
    assert np.allclose(out.data, buf.data)


def test_decay_reduces_amplitude_over_time():
    buf = _tone(440)
    rng = np.random.default_rng(0)
    decay = StemDecayConfig(amp_start_db=0, amp_end_db=-24, lowpass_end_hz=18000,
                            spectral_hole_end=0, dropout_end=0, noise_end_db=-120)
    early = apply_decay(buf, 0.1, decay, rng)
    late = apply_decay(buf, 1.0, decay, rng)
    assert np.max(np.abs(late.data)) < np.max(np.abs(early.data))


def test_stream_hits_target_length():
    loop = _tone(440, secs=0.5)
    target = loop.sr * 3  # 3 seconds from a 0.5s loop
    stream = build_disintegrating_stream(
        loop, target, StemDecayConfig(), crossfade_ms=50, seed=0, stem="mix")
    assert stream.n_frames == target
    assert np.all(np.isfinite(stream.data))


def test_stream_is_deterministic_with_seed():
    loop = _tone(440, secs=0.5)
    target = loop.sr * 2
    a = build_disintegrating_stream(loop, target, StemDecayConfig(), 50, seed=42, stem="mix")
    b = build_disintegrating_stream(loop, target, StemDecayConfig(), 50, seed=42, stem="mix")
    assert np.array_equal(a.data, b.data)


def test_iteration_rng_is_reproducible():
    a = iteration_rng(7, "vocals", 3).standard_normal(8)
    b = iteration_rng(7, "vocals", 3).standard_normal(8)
    assert np.array_equal(a, b)


def test_iteration_rng_differs_across_iteration_stem_and_seed():
    base = iteration_rng(7, "vocals", 3).standard_normal(8)
    assert not np.array_equal(base, iteration_rng(7, "vocals", 4).standard_normal(8))
    assert not np.array_equal(base, iteration_rng(7, "bass", 3).standard_normal(8))
    assert not np.array_equal(base, iteration_rng(8, "vocals", 3).standard_normal(8))


def test_stream_iteration_matches_decayed_iteration():
    """The stream is genuinely built from decayed_iteration outputs.

    Iteration i occupies out[i*stride : i*stride + loop_len]. Its neighbours
    overlap only in the crossfade regions, so [i*stride + xfade, (i+1)*stride]
    is contributed by iteration i alone and must match exactly.
    """
    loop = _tone(440, secs=0.5)
    decay = StemDecayConfig()
    target = loop.sr * 3
    xfade_ms = 50.0

    stream = build_disintegrating_stream(
        loop, target, decay, xfade_ms, seed=11, stem="vocals")
    n_iter, xfade = plan_iterations(loop.n_frames, target, xfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)

    i = 1
    chunk = decayed_iteration(loop, i, n_iter, decay, seed=11, stem="vocals")
    lo = i * stride + xfade
    hi = min((i + 1) * stride, target)
    assert hi > lo, "test setup produced no clean region"
    assert np.allclose(stream.data[lo:hi], chunk.data[xfade:xfade + (hi - lo)], atol=1e-6)
