import numpy as np

from sleepmix import disintegration
from sleepmix.arrangement import Arrangement, Placement
from sleepmix.audio import AudioBuffer
from sleepmix.config import StemDecayConfig
from sleepmix.disintegration import (
    apply_decay, build_disintegrating_stream, decayed_iteration, plan_iterations,
    render_arrangement)
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


def test_planned_iterations_are_all_executed(monkeypatch):
    """``plan_iterations`` counts iterations the renderer runs, not a bound.

    It used to return two more than ``build_disintegrating_stream`` executes,
    which had two consequences that only show up from outside this module: the
    arc never reached ``progress == 1.0`` in output, so a stem never actually
    reached its configured ``*_end`` values; and
    ``preview.preview_iteration_index(session, 1.0)`` returned ``n_iter - 1``,
    an iteration no render produces — so dragging a UI scrubber to maximum
    decay auditioned something that does not exist.

    Reasoning about the loop's break condition is what got this wrong in the
    first place, so this observes the executed iterations instead.

    ``build_disintegrating_stream`` is now a wrapper around
    ``render_arrangement``, which decays each placement through ``apply_decay``
    directly rather than through ``decayed_iteration`` — so the spy watches
    ``apply_decay`` and reads progress off its ``progress`` argument, which
    carries exactly the ``iteration / max(n_iterations - 1, 1)`` value
    ``decayed_iteration`` used to compute.
    """
    executed = []

    def spy(loop, progress, decay, rng):
        executed.append(progress)
        return loop.copy()

    monkeypatch.setattr(disintegration, "apply_decay", spy)

    # (loop seconds, target minutes) — short, medium and realistic-length arcs.
    for loop_secs, target_min in ((0.5, 0.05), (6.0, 2.0), (9.0, 20.0)):
        loop = _tone(220, secs=loop_secs)
        target = int(target_min * 60 * loop.sr)
        xfade_ms = 800.0
        n_iter, _ = plan_iterations(loop.n_frames, target, xfade_ms, loop.sr)

        executed.clear()
        build_disintegrating_stream(
            loop, target, StemDecayConfig(), xfade_ms, seed=0, stem="mix")

        assert len(executed) == n_iter, (
            f"loop={loop_secs}s target={target_min}min: planned {n_iter} "
            f"iterations, executed {len(executed)}")
        assert max(executed) == 1.0, (
            f"loop={loop_secs}s target={target_min}min: the arc stops at "
            f"progress {max(executed):.4f}, never reaching the *_end values")


def test_stream_iteration_matches_decayed_iteration():
    """The stream is genuinely built from the same per-repeat decay.

    Iteration i occupies out[i*stride : i*stride + loop_len]. Its neighbours
    overlap only in the crossfade regions, so [i*stride + xfade, (i+1)*stride]
    is contributed by iteration i alone and must match exactly.

    ``build_disintegrating_stream`` now goes through ``render_arrangement``,
    which decays each placement with ``apply_decay`` keyed by
    ``f"{source_id}:{index}:{stem}"`` (here ``"mix:0:vocals"``) rather than by
    ``stem`` alone, so the comparison is built the same way rather than through
    ``decayed_iteration``, which still uses the old bare-``stem`` key and would
    draw different noise.
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
    progress = i / max(n_iter - 1, 1)
    chunk = apply_decay(loop, progress, decay, iteration_rng(11, "mix:0:vocals", i))
    lo = i * stride + xfade
    hi = min((i + 1) * stride, target)
    assert hi > lo, "test setup produced no clean region"
    assert np.allclose(stream.data[lo:hi], chunk.data[xfade:xfade + (hi - lo)], atol=1e-6)


_FLAT = StemDecayConfig(enabled=False)   # decay off: assert on placement alone


def _plan(starts, seg_frames, target):
    return Arrangement(
        placements=[Placement("s", 0, st, 0.0, seg_frames)
                    for st in starts],
        n_frames=target)


def _dc(sr, secs, value=0.5):
    """A constant-valued buffer — sums and crossfades are readable on it."""
    n = int(sr * secs)
    return AudioBuffer(np.full((n, 1), value, dtype=np.float32), sr)


def test_a_gap_between_repeats_leaves_actual_silence():
    sr = 22050
    seg = _dc(sr, 1.0)
    # second repeat starts a full second after the first ends
    plan = _plan([0, sr * 2], seg.n_frames, sr * 3)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=0.0, seed=0)
    quiet = out.data[sr + 100: sr * 2 - 100]
    assert np.abs(quiet).max() < 1e-6


def test_an_overlap_within_the_crossfade_is_a_crossfade_not_a_sum():
    """Equal-power crossfade of two equal constants stays near the constant.
    Summing them would nearly double it."""
    sr = 22050
    seg = _dc(sr, 1.0, value=0.5)
    xfade_ms = 100.0
    stride = seg.n_frames - int(xfade_ms / 1000.0 * sr)
    plan = _plan([0, stride], seg.n_frames, stride + seg.n_frames)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=xfade_ms, seed=0)
    seam = out.data[stride: stride + int(xfade_ms / 1000.0 * sr)]
    assert seam.max() < 0.75          # nothing like 1.0
    assert seam.min() > 0.4           # and no dip to silence


def test_an_overlap_larger_than_the_crossfade_sums():
    """Deliberate stacking: two voices, not one seam."""
    sr = 22050
    seg = _dc(sr, 1.0, value=0.5)
    plan = _plan([0, sr // 2], seg.n_frames, sr * 2)   # half a segment apart
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=10.0, seed=0)
    stacked = out.data[sr // 2 + 100: sr - 100]
    assert stacked.max() > 0.95       # ~0.5 + 0.5


def test_the_output_is_exactly_the_planned_length():
    sr = 22050
    seg = _dc(sr, 1.0)
    plan = _plan([0, sr, sr * 2], seg.n_frames, sr * 3)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=0.0, seed=0)
    assert out.n_frames == sr * 3


def test_build_disintegrating_stream_still_works():
    """The wrapper keeps every existing caller and test honest."""
    sr = 22050
    seg = _dc(sr, 1.0)
    out = build_disintegrating_stream(
        seg, target_frames=sr * 5, decay=_FLAT, crossfade_ms=100.0,
        seed=0, stem="mix")
    assert out.n_frames == sr * 5
