"""The 'disintegration' engine — the Basinski-flavoured part.

A single seamless loop is repeated many times to fill the target duration. On
each repetition the loop is degraded a little more, with the amount of decay
interpolated from the stem's ``*_start`` to ``*_end`` settings across the whole
mix. Because stems are processed independently, you can let the vocal dissolve
into reverb-ghosts while the harmonic bed stays (almost) intact — the thing you
can't do to a finished stereo master.

All processing here is plain numpy/scipy, so it runs without any ML deps.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from .arrangement import Arrangement, MalformedArrangement, Placement, xfade_frames
from .audio import AudioBuffer
from .config import StemDecayConfig
from .looping import equal_power_crossfade
from .util import db_to_amp, iteration_rng, lerp, shape_progress


def _lowpass(x: np.ndarray, cutoff_hz: float, sr: int) -> np.ndarray:
    """Zero-phase Butterworth lowpass applied per channel."""
    nyq = sr * 0.5
    cutoff = float(np.clip(cutoff_hz, 20.0, nyq * 0.99))
    if cutoff >= nyq * 0.98:
        return x
    sos = signal.butter(4, cutoff / nyq, btype="low", output="sos")
    return signal.sosfiltfilt(sos, x, axis=0).astype(np.float32)


def _apply_dropouts(x: np.ndarray, density: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Punch brief, smoothly-ramped gaps into the signal (tape dropouts)."""
    if density <= 0:
        return x
    n = x.shape[0]
    gap = max(int(0.05 * sr), 1)           # ~50 ms gaps
    n_gaps = int(density * n / gap)
    if n_gaps <= 0:
        return x
    env = np.ones(n, dtype=np.float32)
    ramp = max(int(0.005 * sr), 1)          # 5 ms in/out ramp to avoid clicks
    win = np.hanning(ramp * 2)
    for _ in range(n_gaps):
        start = int(rng.integers(0, max(n - gap, 1)))
        seg = slice(start, start + gap)
        env[seg] = 0.0
        env[start:start + ramp] = win[:ramp][::-1]
        tail = slice(start + gap - ramp, start + gap)
        env[tail] = win[:ramp]
    return x * env[:, None]


def _spectral_holes(x: np.ndarray, fraction: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Zero a random (but fixed-per-call) subset of frequency bins.

    The same bin mask is held across the whole loop so it reads as 'missing
    frequencies' rather than noise."""
    if fraction <= 0:
        return x
    nper = 1024
    f, t, Z = signal.stft(x, fs=sr, nperseg=nper, axis=0)
    n_bins = Z.shape[0]
    mask = rng.random(n_bins) > fraction          # True = keep
    Z = Z * mask[:, None, None]
    _, xrec = signal.istft(Z, fs=sr, nperseg=nper, time_axis=-1, freq_axis=0)
    # istft may return a slightly different length; trim/pad to match.
    xrec = np.moveaxis(xrec, -1, 0)
    out = np.zeros_like(x)
    m = min(out.shape[0], xrec.shape[0])
    out[:m] = xrec[:m]
    return out.astype(np.float32)


def apply_decay(
    loop: AudioBuffer,
    progress: float,
    decay: StemDecayConfig,
    rng: np.random.Generator,
) -> AudioBuffer:
    """Return ``loop`` degraded to the level implied by ``progress`` (0..1)."""
    if not decay.enabled or progress <= 0:
        return loop.copy()

    p = shape_progress(progress, decay.curve)
    x = loop.data.astype(np.float32)
    sr = loop.sr

    # 1. High-frequency erosion.
    cutoff = lerp(decay.lowpass_start_hz, decay.lowpass_end_hz, p)
    x = _lowpass(x, cutoff, sr)

    # 2. Spectral holes (missing frequencies).
    frac = lerp(decay.spectral_hole_start, decay.spectral_hole_end, p)
    x = _spectral_holes(x, frac, sr, rng)

    # 3. Dropouts.
    density = lerp(decay.dropout_start, decay.dropout_end, p)
    x = _apply_dropouts(x, density, sr, rng)

    # 4. Amplitude fade.
    gain = db_to_amp(lerp(decay.amp_start_db, decay.amp_end_db, p))
    x = x * gain

    # 5. Rising noise floor (tape hiss).
    noise_amp = db_to_amp(lerp(decay.noise_start_db, decay.noise_end_db, p))
    if noise_amp > 1e-6:
        x = x + rng.standard_normal(x.shape).astype(np.float32) * noise_amp

    return AudioBuffer(x, sr)


def plan_iterations(
    loop_frames: int, target_frames: int, crossfade_ms: float, sr: int
) -> tuple[int, int]:
    """Return ``(n_iterations, xfade_frames)`` for a stream of this shape.

    Has no production caller left — ``run_pipeline`` goes through
    ``plan_arrangement``/``render_arrangement``, and the preview reads that same
    plan rather than calling this. Retained on purpose, as the regression oracle
    ``tests/test_arrangement.py::test_defaults_reproduce_todays_positions`` checks
    the planner against: at default gaps the planner must land on exactly the
    frames and exactly the count this produces, and that equality is not
    re-derivable from the new code once this is gone.

    The count is the number of iterations the renderer *executes*, not an upper
    bound on them. Iteration ``i`` leaves the write head at
    ``loop_frames + i * stride``, so the first index at or past ``target_frames``
    — the one the builder stops on — is ``ceil((target - xfade) / stride) - 1``.
    An earlier version added one here, which put ``n_iterations - 1`` a full
    iteration beyond anything the render produces: the arc never reached
    ``progress == 1.0`` in output, and a preview scrubbed to maximum decay
    auditioned an iteration that does not exist in any render."""
    xfade = xfade_frames(crossfade_ms, loop_frames, sr)
    stride = max(loop_frames - xfade, 1)
    n_iter = int(np.ceil((target_frames - xfade) / stride))
    return max(n_iter, 1), xfade


def decayed_iteration(
    loop: AudioBuffer,
    iteration: int,
    n_iterations: int,
    decay: StemDecayConfig,
    seed: int,
    stem: str,
    source_id: str = "mix",
    index: int = 0,
    progress: float | None = None,
) -> AudioBuffer:
    """The loop as it sounds on repetition ``iteration`` of ``n_iterations``.

    This is the **only** place the decay rng key is composed —
    ``f"{source_id}:{index}:{stem}"``, further keyed by ``iteration`` through
    ``util.iteration_rng``. It used to be composed a second time, inline,
    where ``render_arrangement`` called ``apply_decay`` directly; that split
    the render and preview paths onto two different keys without either of
    them changing in a way that looked wrong, and ``preview.py``'s own module
    docstring is explicit that a preview must be *exactly* reproducible
    against the render, not merely close to it. Composing the key in exactly
    one function is what makes that true again, and keeps it true: nothing
    else may build this string independently.

    ``source_id``/``index`` default to ``"mix"``/``0`` — the one source and
    segment every caller deals with today — so call sites that only vary by
    ``stem`` (every one that existed before the arrangement) need no changes.

    ``progress`` defaults to ``iteration / max(n_iterations - 1, 1)``, the
    even-spacing formula every caller used before arrangement plans existed.
    A caller that already knows the authoritative progress for this repeat —
    ``render_arrangement``, reading ``Placement.decay_progress`` off a plan
    that may not space repeats evenly — should pass it explicitly rather than
    let this recompute an approximation that only happens to agree today."""
    p = progress if progress is not None else iteration / max(n_iterations - 1, 1)
    key = f"{source_id}:{index}:{stem}"
    return apply_decay(loop, p, decay, iteration_rng(seed, key, iteration))


def render_arrangement(
    loop: AudioBuffer,
    plan: Arrangement,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
    """Render every placement in ``plan``, each decayed to its own progress.

    **The seam rule.** Consecutive repeats can now relate three ways, and only
    one of them is the join this renderer used to assume. An overlap no larger
    than the crossfade is a seam and gets an equal-power crossfade, exactly as
    before. An overlap *larger* than the crossfade is deliberate stacking —
    the operator asked for two voices — and is summed, because crossfading it
    would duck both through the overlap, which is the opposite of playing over
    each other. A gap gets nothing, and the silence is the point.

    The crossfade branch blends against the *previous placement's own
    chunk*, not against whatever the accumulator holds, and adds the
    difference in:
    ``out[region] += crossfade(prev_tail, chunk[:overlap]) - prev_tail``,
    where ``prev_tail`` is the previous placement's own last ``overlap``
    samples — never anything the accumulator has already mixed in. Whatever
    else already sits in that region — placement i-2, i-3, any number of
    earlier voices the additive branch stacked there — is left exactly as it
    was, because the delta only ever replaces placement i-1's own
    contribution: for any existing content ``d``,
    ``d + prev_tail + (crossfade(prev_tail, b) - prev_tail) = d +
    crossfade(prev_tail, b)``. That holds regardless of how many earlier
    placements overlap the region, so it is additive-safe by construction —
    not because of any argument about how far back an overlap can reach.
    (An earlier version of this docstring made exactly that argument, from
    the crossfade branch's overlap bound alone, and it was wrong: that bound
    constrains only the stride into this placement, not the stride into the
    one before it, so a heavy stack — small stride, additive branch —
    immediately followed by a seam — large stride, crossfade branch — is
    reachable, including from ``plan_arrangement`` at its own default
    settings. ``test_a_seam_after_a_stack_keeps_the_stacked_voice`` pins down
    the case that argument would have silently dropped.) The formula reduces
    to the old plain assignment exactly when the region truly holds nothing
    but placement i-1's contribution, so nothing that already passed on that
    basis changes.

    Heavier stacking than the crossfade window takes the additive branch,
    where nothing is overwritten or subtracted.

    Every placement is decayed through ``decayed_iteration`` rather than
    ``apply_decay`` directly, so this and ``preview.render_window`` compose
    the rng key the same way and cannot drift apart — see
    ``decayed_iteration``'s docstring for why that split happened once
    already and must not happen again.

    Raises ``MalformedArrangement`` for a placement that does not fit the
    buffer this builds, rather than letting the write below fail as a bare
    numpy broadcast error. ``plan_arrangement`` is not supposed to produce
    one — see its own docstring — so this is a cheap precondition check
    guarding against whatever else might hand this an ``Arrangement``, not a
    replacement for that fix."""
    sr = loop.sr
    ch = loop.n_channels
    seg_len = loop.n_frames
    xfade = xfade_frames(crossfade_ms, seg_len, sr)

    out = np.zeros((plan.n_frames + seg_len, ch), dtype=np.float32)
    prev_end = None
    prev_chunk = None
    for i, placement in enumerate(plan.placements):
        if cancel is not None:
            cancel.check()
        start = placement.start_frame
        # A precondition, not validation: plan_arrangement's own stopping
        # rule keeps every start short of target_frames, so this should
        # never fire from a plan it produced. It exists for whatever else
        # might hand this an Arrangement it didn't build, so a malformed one
        # fails with a named placement and reason instead of a numpy
        # broadcast-shape error out of the write below.
        if start < 0 or start + seg_len > out.shape[0]:
            raise MalformedArrangement(
                f"placement {i} (source {placement.source_id!r} index "
                f"{placement.index}) starts at frame {start}, which does "
                f"not fit the {out.shape[0]}-frame buffer built for a "
                f"{plan.n_frames}-frame arrangement")
        chunk = decayed_iteration(
            loop, i, len(plan.placements), decay, seed, stem,
            source_id=placement.source_id, index=placement.index,
            progress=placement.decay_progress,
        ).data
        overlap = 0 if prev_end is None else max(prev_end - start, 0)
        if 0 < overlap <= xfade:
            prev_tail = prev_chunk[-overlap:]
            blended = equal_power_crossfade(prev_tail, chunk[:overlap])
            out[start:start + overlap] += blended - prev_tail
            out[start + overlap:start + seg_len] += chunk[overlap:]
        else:
            out[start:start + seg_len] += chunk
        prev_end = start + seg_len
        prev_chunk = chunk

    return AudioBuffer(out[:plan.n_frames], sr)


def build_disintegrating_stream(
    loop: AudioBuffer,
    target_frames: int,
    decay: StemDecayConfig,
    crossfade_ms: float,
    seed: int,
    stem: str = "mix",
    cancel=None,
) -> AudioBuffer:
    """Repeat ``loop`` back to back until ``target_frames``, degrading each pass.

    Retained as the zero-gap case of ``render_arrangement``, which is what
    every caller predating the arrangement wants and what
    ``tests/test_disintegration.py`` already pins down."""
    n_iter, xfade = plan_iterations(loop.n_frames, target_frames, crossfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)
    last = max(n_iter - 1, 1)
    plan = Arrangement(
        placements=[
            Placement("mix", 0, i * stride, i / last, loop.n_frames)
            for i in range(n_iter)
        ],
        n_frames=target_frames,
    )
    return render_arrangement(loop, plan, decay, crossfade_ms, seed, stem, cancel)
