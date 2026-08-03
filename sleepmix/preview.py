"""Render one point in the decay arc, without rendering what precedes it.

``apply_decay`` is a pure function of progress — iteration 400 does not depend
on iterations 1..399 — so auditioning "what does this sound like two thirds of
the way through" costs a single loop iteration rather than twenty minutes. That
is the whole basis of interactive tuning here.

A preview is always a *specific iteration*: the one nearest the requested point
in the arc. That makes it exactly reproducible against the corresponding part of
a full render (pre-reverb), rather than an approximation of it.
"""
from __future__ import annotations

import numpy as np

from .audio import AudioBuffer, silence
from .config import StemConfig
from .disintegration import decayed_iteration, plan_iterations
from .effects import apply_reverb
from .session import RenderSession
from .util import db_to_amp


def preview_iteration_index(session: RenderSession, progress: float) -> tuple[int, int]:
    """Map a point in the arc to ``(iteration, n_iterations)``.

    Uses the same ``plan_iterations`` the batch renderer uses, so the mapping
    cannot drift between preview and render."""
    cfg = session.config
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    n_iter, _ = plan_iterations(
        loop.n_frames, target_frames, cfg.output.cycle_crossfade_ms, loop.sr)
    p = float(np.clip(progress, 0.0, 1.0))
    return int(round(p * (n_iter - 1))), n_iter


def render_window(
    session: RenderSession,
    progress: float,
    stems: list[str] | None = None,
    reverb: bool = True,
) -> AudioBuffer:
    """One loop iteration at ``progress``, summed over ``stems``.

    ``stems`` defaults to every stem the session has. Pass a subset to solo."""
    cfg = session.config
    names = stems if stems is not None else session.stem_names()
    iteration, n_iter = preview_iteration_index(session, progress)

    acc: np.ndarray | None = None
    sr = 0
    for name in names:
        sc = _stem_config(cfg.stems, name)
        if not sc.enabled:
            continue
        loop = session.prepared_loop(name)
        sr = loop.sr
        chunk = decayed_iteration(loop, iteration, n_iter, sc.decay, cfg.seed, name)
        x = chunk.with_channels(cfg.output.channels).data
        if abs(sc.gain_db) > 1e-6:
            x = x * db_to_amp(sc.gain_db)
        if acc is None:
            acc = x.copy()
        else:
            m = min(acc.shape[0], x.shape[0])
            acc[:m] += x[:m]

    if acc is None:
        return silence(1, cfg.output.channels, cfg.output.sample_rate)

    out = AudioBuffer(acc, sr)
    if reverb:
        out = apply_reverb(out, cfg.reverb)
    return out


def _stem_config(configured: list[StemConfig], name: str) -> StemConfig:
    """The configured stem, or defaults when the session has a stem the config
    doesn't mention (e.g. the single 'mix' stem from the no-Demucs fallback)."""
    for sc in configured:
        if sc.name == name:
            return sc
    return StemConfig(name=name)
