"""Render one point in the decay arc, without rendering what precedes it.

``apply_decay`` is a pure function of progress — iteration 400 does not depend
on iterations 1..399 — so auditioning "what does this sound like two thirds of
the way through" costs a single loop iteration rather than twenty minutes. That
is the whole basis of interactive tuning here.

A preview is always a *specific iteration*: the one nearest the requested point
in the arc. That makes it exactly reproducible against the corresponding part of
a full render (pre-reverb), rather than an approximation of it.

The window is also meant to be *played on loop* by the UI while you tune, which
constrains reverb: a window is exactly one loop iteration long, no longer, and
must not open with a block of silence, or every cycle would gap and click. See
``_reverbed_window``.
"""
from __future__ import annotations

import numpy as np

from .arrangement import (
    SegmentInfo, concurrent_placements, decay_amplitude_proxy, densest_frame,
    plan_arrangement, xfade_frames)
from .audio import AudioBuffer
from .config import MixConfig, NothingToRender, StemConfig, plan_stem_configs
from .disintegration import decayed_iteration
from .effects import apply_reverb, reverb_dry_offset
from .session import RenderSession
from .soundbed import build_soundbed
from .util import db_to_amp


def preview_iteration_index(session: RenderSession, progress: float) -> tuple[int, int]:
    """Map a point in the arc to ``(index, n_placements)``.

    Reads the same ``plan_arrangement`` the renderer does, so the mapping
    cannot drift between preview and render. It used to read
    ``plan_iterations``, which is correct only when every repeat sits one
    stride from the last — with a gap the render produces fewer repeats, and
    a preview scrubbed to the end would audition one that does not exist."""
    cfg = session.config
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    # source_id/index are inert here: plan_arrangement uses them only to label
    # each Placement, and the count this function wants comes from len(...),
    # which depends on n_frames alone. Set to the render pipeline's own values
    # anyway, not because this call site needs them today, but so it is
    # already correct once a later plan gives segments real identities and
    # decayed_iteration starts reading them instead of its "mix"/0 defaults.
    plan = plan_arrangement(
        [SegmentInfo(source_id="mix", index=0, n_frames=loop.n_frames)],
        cfg, target_frames, loop.sr)
    n = len(plan.placements)
    p = float(np.clip(progress, 0.0, 1.0))
    return int(round(p * (n - 1))), n


def master_gain(session: RenderSession, reverb: bool = True) -> float:
    """The gain that puts a ``reverb``-path window at the render's level.

    A preview is one window of a stream that gets peak-normalized as a whole.
    Without this correction a preview plays about 4 dB above the render it
    represents — and louder reads as *less decayed*, which corrupts exactly the
    judgement a preview exists to support. Found by listening; no test caught it,
    because the bit-identity check compares pre-reverb and pre-master.

    Calibrated per signal path, hence the flag. Reverb changes the peak, so a
    factor measured wet and applied to a dry window mis-levels it — measured at
    the default reverb config, a dry window mastered with the wet factor sits
    3.20 dB *low*, which is the same defect pointing the other way: quieter
    reads as *more* decayed. So the calibration window is rendered down the same
    path the caller asked for, and the two factors are cached separately.

    Which window to measure used to be assumed rather than chosen: decay only
    removes energy, so the peak fell monotonically across the arc and
    iteration 0 was the loudest window this module could produce. A negative
    gap large enough to overlap repeats by more than the crossfade width
    breaks that — two near-fresh repeats genuinely sounding together (summed
    by ``render_arrangement``'s additive branch) beat one fresh repeat alone.
    An *ordinary* seam does not: consecutive repeats always geometrically
    overlap by exactly the crossfade width, at every config including the
    default, and ``render_arrangement`` blends that into one voice, not two.
    ``arrangement.densest_frame`` (and the ``concurrent_placements`` it's
    built on) draws exactly that distinction — see their docstrings — so it
    finds the frame carrying the most *genuinely concurrent* amplitude, not
    merely the most geometric overlap. This measures a real window at the
    progress of whichever placement dominates there — the freshest one, since
    ``render_window`` renders exactly one loop iteration and has no way to
    render two placements sounding together at once.

    What that single window's peak is missing is scaled back in rather than
    ignored: the measured peak is multiplied by the ratio of the summed
    amplitude proxy over every placement concurrent (in that same
    seam-excluding sense) at the densest frame to the proxy of the one
    placement actually rendered. With no overlap beyond an ordinary seam —
    which includes every default config — exactly one placement is concurrent
    there, the ratio is 1.0, and this is bit-identical to measuring iteration
    0 alone, as it always was.

    This is an estimate, not a prediction. Repeats of the same loop at
    different decay stages are the same material at different points in its
    decay, not independent sources, so summing their amplitude proxies is an
    upper-ish bound on how loud they truly sum to rather than the render's
    actual peak. That looseness is acceptable here because of what this
    factor is *for*: the real render is peak-normalized properly, from the
    genuine rendered audio, by ``run_pipeline``'s ``normalize_peak`` — this
    only has to put a preview window at roughly the render's level, not
    protect the render from clipping. (A whole render's loudest moment is
    also not necessarily the densest frame this proxy finds — fades and
    inter-iteration crossfades move it too; see the level-matching entry in
    ``docs/project-state.md``.)"""
    cached = session.master_gain.get(reverb)
    if cached is None:
        cfg = session.config
        name = session.stem_names()[0]
        loop = session.prepared_loop(name)
        target_frames = int(cfg.output.duration_min * 60 * loop.sr)
        plan = plan_arrangement(
            [SegmentInfo(source_id="mix", index=0, n_frames=loop.n_frames)],
            cfg, target_frames, loop.sr)
        decay = cfg.stems[0].decay
        xfade = xfade_frames(cfg.output.cycle_crossfade_ms, loop.n_frames, loop.sr)
        frame = densest_frame(plan, decay, xfade)
        here = concurrent_placements(plan, frame, xfade)
        # here is never empty: densest_frame's candidates are placement start
        # frames, and a placement's effective span always contains its own
        # start (see concurrent_placements / _effective_spans).
        dominant = min(here, key=lambda p: p.decay_progress)
        loudest = render_window(
            session, dominant.decay_progress, reverb=reverb, master=False)
        peak = float(np.abs(loudest.data).max())
        single = decay_amplitude_proxy(dominant.decay_progress, decay)
        total = sum(decay_amplitude_proxy(p.decay_progress, decay) for p in here)
        density_ratio = total / single if single > 1e-12 else 1.0
        effective_peak = peak * density_ratio
        target = db_to_amp(session.config.output.peak_db)
        cached = float(target / effective_peak) if effective_peak > 1e-9 else 1.0
        session.master_gain[reverb] = cached
    return cached


def render_window(
    session: RenderSession,
    progress: float,
    stems: list[str] | None = None,
    reverb: bool = True,
    master: bool = True,
) -> AudioBuffer:
    """One loop iteration at ``progress``, summed over ``stems``, master-matched
    to the render by default.

    ``stems`` defaults to every stem the batch renderer would process. Pass a
    subset to solo; names outside that set are ignored, because previewing a
    stem the render would drop is exactly the lie this module exists to avoid.

    Raises ``NothingToRender`` when that leaves nothing to render — every stem
    switched off, or a solo naming only stems the render would drop. Both are
    user errors with a nameable cause, and both used to produce a one-frame WAV:
    a well-formed file that plays silence and says nothing about why. Silence
    that looks like success is the worst answer this module can give, because
    nobody in the loop can hear that it is wrong.

    Each stem is decayed, reverbed with its own send, gained and channel-mapped
    in the same order as ``pipeline._process_stem`` — reverb is not linear
    across differing wet scales, so summing dry and reverbing once would not
    match the render.

    When ``cfg.soundbed.enabled`` and ``stems is None``, a bed is mixed in
    after the stems are summed — the same position ``run_pipeline`` mixes it
    in, before mastering. Omitted for a solo (see the comment at the call
    site) and generated fresh per window rather than sliced from a
    full-length one; both are deliberate, not gaps.

    ``master=True`` (the default) applies one gain factor to every window,
    computed once per ``reverb`` setting via ``master_gain`` and memoized on
    the session — see that function's docstring for why a preview needs this
    at all.

    With ``reverb=True`` that factor is the one ``run_pipeline`` would apply,
    since every real render reverbs. With ``reverb=False`` there is no render
    to match: the result is a *level-matched view of the dry path* — the same
    signal a wet mastered window carries underneath its reverb, at the same
    scale — not a simulation of any render that could actually be produced."""
    cfg = session.config
    planned = plan_stem_configs(session.stem_names(), cfg)
    if not planned:
        raise NothingToRender(
            "Every stem is switched off, so there is nothing to preview. "
            "Enable at least one stem.")
    if stems is not None:
        wanted = set(stems)
        planned = [sc for sc in planned if sc.name in wanted]
        if not planned:
            raise NothingToRender(
                "Nothing to preview — none of the soloed stems ("
                + ", ".join(sorted(wanted))
                + ") is one this render would process. A stem that is switched "
                  "off, or one separation did not produce, cannot be soloed.")
    iteration, n_iter = preview_iteration_index(session, progress)

    acc: np.ndarray | None = None
    sr = 0
    for sc in planned:
        loop = session.prepared_loop(sc.name)
        sr = loop.sr
        chunk = decayed_iteration(loop, iteration, n_iter, sc.decay, cfg.seed, sc.name)
        if reverb:
            chunk = _reverbed_window(loop, chunk, iteration, n_iter, sc, cfg)
        if abs(sc.gain_db) > 1e-6:
            chunk = AudioBuffer(chunk.data * db_to_amp(sc.gain_db), chunk.sr)
        x = chunk.with_channels(cfg.output.channels).data
        if acc is None:
            acc = x.copy()
        else:
            m = min(acc.shape[0], x.shape[0])
            acc[:m] += x[:m]

    if acc is None:
        # Unreachable: ``planned`` is non-empty by the time the loop starts and
        # every iteration assigns ``acc``. A raise rather than the one-frame
        # ``silence`` this used to return — a 48-byte WAV behind a 200 is the
        # same silent failure the two checks above exist to stop, wearing a
        # different hat.
        raise NothingToRender("Nothing to preview — no stem produced any audio.")

    out = AudioBuffer(acc, sr)

    # Where run_pipeline puts it: after the stems are summed, before mastering.
    #
    # Generated for this window rather than sliced out of a full-length bed.
    # The noise is stationary and the binaural beat is periodic, so a window's
    # worth is perceptually the same as the matching slice of twenty minutes —
    # and building twenty minutes to take twenty seconds would be absurd.
    #
    # Seeded from the config rather than left freshly random, because
    # ``master_gain`` memoises a factor measured from one window and a random
    # window would make that factor depend on which draw happened. Note this
    # does *not* reproduce the render's own bed sample for sample:
    # ``run_pipeline``'s generator has advanced by the time it reaches the bed.
    # Noise is noise, so that is inaudible — but it is not the same signal.
    #
    # Skipped for a solo, which already does not match the render (the render
    # has every enabled stem). A bed over an isolated stem masks the thing it
    # was isolated to hear.
    if stems is None and cfg.soundbed.enabled:
        bed = build_soundbed(out.data.shape[0] / sr, sr, cfg.soundbed,
                             np.random.default_rng(cfg.seed))
        wide = bed.with_channels(cfg.output.channels).data
        n = min(out.data.shape[0], wide.shape[0])
        out = AudioBuffer(out.data[:n] + wide[:n], sr)

    if master:
        # One factor for every window, never per-window normalization: the arc
        # survives only because later windows stay genuinely quieter.
        out = AudioBuffer(out.data * master_gain(session, reverb), sr)
    return out


def _reverbed_window(
    loop: AudioBuffer,
    chunk: AudioBuffer,
    iteration: int,
    n_iterations: int,
    sc: StemConfig,
    cfg: MixConfig,
) -> AudioBuffer:
    """Reverb one iteration and hand back a window that still loops.

    Reverbing the iteration on its own is the obvious thing and it is wrong in
    two ways at once, both fatal to the UI's use for this buffer — playing it on
    a loop. ``effects._predelay`` *prepends* the pre-delay (40ms by default), so
    the result is longer than the loop and opens with silence: a gap and a click
    on every cycle.

    Both follow from reverbing a fragment as though nothing preceded it. So
    something does: the preceding iteration is rendered as leading context,
    reverbed together with this one, and then this one is cut back out. What
    lands in the pre-delay region is then the previous iteration's reverb
    tail — the bleed a real render has and an isolated window does not, which
    is what the spec asked for. Iteration 0 genuinely has nothing before it, so
    it gets no context; the trim still removes the leading silence.

    The cut point comes from ``effects.reverb_dry_offset``, measured against
    whichever backend is installed, so the returned frames carry this
    iteration's dry signal sample-aligned with the ``reverb=False`` window.
    The result is exactly ``chunk.n_frames`` long, always.

    Known approximation: the context is *concatenated*, where a real render
    crossfades consecutive iterations over ``cycle_crossfade_ms``. The reverb
    therefore hears a small discontinuity at the join that the render does not.
    The window remains representative rather than bit-identical with reverb on,
    as ``docs/project-state.md`` records.
    """
    n = chunk.n_frames
    if iteration > 0:
        context = decayed_iteration(
            loop, iteration - 1, n_iterations, sc.decay, cfg.seed, sc.name).data
    else:
        context = np.zeros((0, chunk.n_channels), dtype=np.float32)

    joined = AudioBuffer(np.concatenate([context, chunk.data], axis=0), chunk.sr)
    wet = apply_reverb(joined, cfg.reverb, wet_scale=sc.reverb_send)

    start = context.shape[0] + reverb_dry_offset(cfg.reverb, chunk.sr)
    out = wet.data[start:start + n]
    if out.shape[0] < n:
        # No backend should come up short — both return ``frames + predelay`` —
        # but a window one frame shy of the loop would click, so pad rather than
        # trust it.
        out = np.concatenate(
            [out, np.zeros((n - out.shape[0], out.shape[1]), dtype=np.float32)],
            axis=0)
    return AudioBuffer(out, chunk.sr)
