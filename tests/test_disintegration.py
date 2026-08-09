import numpy as np
import pytest

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
    ``render_arrangement``, which still decays every placement through
    ``decayed_iteration`` — the one function allowed to compose the decay rng
    key — so the spy watches that, as it always did. ``render_arrangement``
    passes ``progress`` explicitly (read off the plan), so the spy reads it
    from that keyword argument rather than recomputing it, but the value is
    the same ``iteration / max(n_iterations - 1, 1)`` either way for the
    even-stride plan ``build_disintegrating_stream`` builds.
    """
    executed = []

    def spy(loop, iteration, n_iterations, decay, seed, stem,
             source_id="mix", index=0, progress=None):
        p = progress if progress is not None else iteration / max(n_iterations - 1, 1)
        executed.append(p)
        return loop.copy()

    monkeypatch.setattr(disintegration, "decayed_iteration", spy)

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
    """The stream is genuinely built from decayed_iteration outputs.

    Iteration i occupies out[i*stride : i*stride + loop_len]. Its neighbours
    overlap only in the crossfade regions, so [i*stride + xfade, (i+1)*stride]
    is contributed by iteration i alone and must match exactly.

    ``build_disintegrating_stream`` goes through ``render_arrangement``, which
    decays every placement through ``decayed_iteration`` — the single place
    the rng key is composed — with ``source_id="mix"``, ``index=0``, matching
    this call's defaults, so the two sides draw the same noise.
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


def test_a_seam_after_a_stack_keeps_the_stacked_voice():
    """A voice already stacked into a region must survive a later seam.

    Placement 0 and 1 overlap by more than the crossfade (a deliberate
    stack, the additive branch); placement 1 and 2 then overlap by less than
    it (a seam, the crossfade branch). Every test above this one uses two
    placements, or three with no overlap, so none of them can catch this:
    the crossfade must replace only placement 1's contribution to the seam
    region, leaving placement 0's still-live tail underneath it untouched.

    Assigning into the region instead of blending against the previous
    placement's own chunk — the bug this pins down — crossfades whatever the
    accumulator already holds there, placement 0's tail included, against
    placement 2. That quietly ramps placement 0 down to nothing across the
    seam and snaps it back to full level immediately past it: lost audio and
    a discontinuity that clicks.

    All three placements share one constant-valued loop (decay is off), so
    the region's level is exact and reproducible rather than approximate:
    correct, ``out[16537:22050]`` averages placement 0's constant 0.5 plus
    an equal-power blend of placements 1 and 2 (also 0.5 each), ≈1.144.
    Measured directly against the pre-fix code, the same region instead
    averages ≈1.082 — placement 0 folded into the blend rather than left
    standing beneath it. The threshold below sits between the two with
    margin on both sides."""
    sr = 22050
    seg = _dc(sr, 1.0, value=0.5)
    plan = _plan([0, 4410, 16537], seg.n_frames, sr * 3)
    out = render_arrangement(seg, plan, _FLAT, crossfade_ms=500.0, seed=0)
    region = out.data[16537:22050]
    assert region.mean() > 1.10, (
        f"region mean {region.mean():.4f} is at or below the level a "
        "seam that drops the stacked voice would produce (~1.082); "
        "placement 0's tail did not survive the crossfade with placement 2")


def test_the_amplitude_proxy_matches_what_apply_decay_actually_does():
    """``arrangement.decay_amplitude_proxy`` models this function. Check it.

    The proxy exists to rank and weight placements for ``densest_frame`` and
    ``preview.master_gain``, and it is only worth anything if it agrees with
    the amplitude ``apply_decay`` really applies. It did not, at one point:
    ``apply_decay`` short-circuits on ``progress <= 0`` and hands back the
    loop untouched, while the proxy returned ``db_to_amp(amp_start_db)``
    there. Invisible on a falling arc from the default 0 dB — both are 1.0 —
    and inverted on a rising one.

    Measured rather than argued: a constant-valued buffer through
    ``apply_decay`` with everything *except* the amplitude stage turned off
    (lowpass parked above the working Nyquist so ``_lowpass`` passes it
    through, no holes, no dropouts, noise floor inaudible) comes out scaled
    by exactly the gain the arc asks for, so the output/input ratio is the
    ground truth the proxy has to reproduce. Progress 0 is in the list on
    purpose — it is the case that was wrong."""
    from sleepmix.arrangement import decay_amplitude_proxy

    sr = 22050
    buf = AudioBuffer(np.full((sr, 1), 0.5, dtype=np.float32), sr)
    for start, end in ((0.0, -16.0), (-30.0, -16.0), (-40.0, -24.0)):
        decay = StemDecayConfig(
            curve="linear", lowpass_start_hz=20000.0, lowpass_end_hz=20000.0,
            spectral_hole_start=0.0, spectral_hole_end=0.0,
            dropout_start=0.0, dropout_end=0.0,
            noise_start_db=-200.0, noise_end_db=-200.0,
            amp_start_db=start, amp_end_db=end)
        for progress in (0.0, 0.25, 0.5, 1.0):
            out = apply_decay(buf, progress, decay, np.random.default_rng(0))
            actual = float(np.abs(out.data).max()) / 0.5
            assert decay_amplitude_proxy(progress, decay) == pytest.approx(
                actual, rel=1e-5), (
                f"proxy disagrees with apply_decay at progress {progress} on "
                f"the arc {start} -> {end} dB")
