import time

import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig, StemConfig
from sleepmix import disintegration
from sleepmix.disintegration import (
    build_disintegrating_stream, decayed_iteration, plan_iterations)
from sleepmix.effects import apply_reverb, reverb_dry_offset
from sleepmix.pipeline import run_pipeline
from sleepmix.preview import preview_iteration_index, render_window
from sleepmix.session import RenderSession


def _song(path, sr=22050, secs=6.0):
    t = np.arange(int(sr * secs)) / sr
    y = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330)) / 4.0
    save_audio(AudioBuffer(np.stack([y, y], axis=1).astype(np.float32), sr), str(path))


def _session(tmp_path, sep):
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    return RenderSession(str(song), cfg, separate_fn=sep)


def test_window_matches_decayed_iteration_pre_reverb(tmp_path, stub_separation):
    """The preview is the same computation the render performs.

    Compared pre-reverb because reverb is applied per-window here and has no
    tail from the preceding iteration — see the fidelity caveat in the spec."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]

    progress = 0.7
    out = render_window(s, progress, stems=[name], reverb=False, master=False)
    i, n = preview_iteration_index(s, progress)
    expected = decayed_iteration(
        s.prepared_loop(name), i, n, s.config.stems[0].decay, s.config.seed, name)
    assert np.array_equal(out.data, expected.data)


def test_window_matches_what_the_renderer_actually_produces(tmp_path, stub_separation):
    """The preview equals the render — checked against a real ``run_pipeline``.

    The other equality test compares ``render_window`` against
    ``decayed_iteration``, which is the call ``render_window`` makes internally;
    it can prove stem selection, gain and channel mapping happen, but it never
    invokes the renderer, so it cannot prove the two paths agree. The equality
    actually rests on invariants nothing else enforces: that
    ``session.prepared_loop`` and ``pipeline._process_stem`` perform
    ``slice_loop → make_seamless → slow_and_pitch`` in the *same order*, and
    that ``preview_iteration_index`` deriving ``target_frames`` from
    ``loop.sr`` agrees with ``run_pipeline`` deriving it from ``work_sr``.
    Reorder two lines in one file and every other test still passes while the
    preview quietly lies. This one fails.

    Geometry is the same one ``test_stream_iteration_matches_decayed_iteration``
    uses: iteration *i* alone contributes to
    ``[i*stride + xfade, (i+1)*stride]``.

    Mastering is configured out of the way — output rate matched to the working
    rate so no resample, fades at zero, a middle iteration so fades would be
    irrelevant anyway, and reverb reduced to a pre-delay-free dry gain. What
    survives is two constant scale factors (reverb's dry level and the
    peak-normalize), so both sides are normalized before comparison.
    """
    song = tmp_path / "s.wav"
    out = tmp_path / "mix.wav"
    _song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.5
    cfg.output.sample_rate = 22050     # == the stub's rate: mastering won't resample
    cfg.output.fade_in_s = 0.0
    cfg.output.fade_out_s = 0.0
    cfg.reverb.wet = 0.0               # reverb collapses to a flat dry gain…
    cfg.reverb.predelay_ms = 0.0       # …with no shift to realign
    cfg.soundbed.enabled = False

    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    name = session.stem_names()[0]
    cfg.stems = [StemConfig(name=name)]

    rendered = run_pipeline(str(song), cfg, str(out), progress=lambda *_: None)

    loop = session.prepared_loop(name)
    target = int(cfg.output.duration_min * 60 * loop.sr)
    n_iter, xfade = plan_iterations(
        loop.n_frames, target, cfg.output.cycle_crossfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)
    assert n_iter >= 4, "need a middle iteration clear of both fades"

    i = n_iter // 2
    progress = i / (n_iter - 1)
    assert preview_iteration_index(session, progress)[0] == i

    window = render_window(session, progress, stems=[name], reverb=False)
    lo = i * stride + xfade
    hi = min((i + 1) * stride, target)
    assert hi > lo, "test setup produced no crossfade-free region"

    a = rendered.data[lo:hi]
    b = window.data[xfade:xfade + (hi - lo)]
    a = a / np.max(np.abs(a))
    b = b / np.max(np.abs(b))
    err = float(np.max(np.abs(a - b)))
    # Not exact equality: the render multiplies through reverb's dry level and
    # the peak-normalize, two extra float32 rounds the preview never performs.
    # Measured deviation is 1.192e-07 — one float32 ULP at unit magnitude
    # (2**-23). The bound below is that, with a little headroom, and nothing
    # like enough slack to hide a real divergence: swapping two stages in
    # ``session.prepared_loop`` moves this to 1.157e+00.
    assert err < 1e-6, f"preview and render disagree by {err:.3e}"


def test_the_preview_and_render_paths_compose_the_same_rng_key(
        tmp_path, stub_separation, monkeypatch):
    """Names the invariant every test above this one relies on without ever
    stating it: preview and render must key their decay randomness the same
    way, or a preview auditions noise the render does not produce.

    ``decayed_iteration`` is the one place that key is composed —
    ``f"{source_id}:{index}:{stem}"`` — but the two paths only ever reach it
    through values that happen to agree today, declared nowhere as a pair:
    ``render_window`` never states ``source_id``/``index``, relying on
    ``decayed_iteration``'s ``"mix"``/``0`` defaults; ``build_disintegrating_stream``
    states them explicitly via ``Placement("mix", 0, ...)``. When those two
    silently diverged earlier in this branch's history, the symptom three
    tests away was ``err = 1.2e+00`` — a number that says nothing about an
    rng key. A later plan gives sources real ids and segments real indices,
    which is exactly the kind of change that could reintroduce this
    divergence. This test fails here first when it does, with a message
    that names the actual mismatch instead of a bare tolerance miss.

    Captured by spying on ``disintegration.iteration_rng``, which
    ``decayed_iteration`` calls with the composed key as its second
    argument — so this observes the real key each path uses rather than
    re-deriving the format and risking a second place that must agree with
    the first. The spy still delegates to the real ``iteration_rng``, so
    both calls run for real rather than being stubbed out."""
    from sleepmix.util import iteration_rng as real_iteration_rng

    keys: dict[str, str] = {}
    current = {"label": None}

    def spy(seed, key, iteration):
        if current["label"] is not None:
            keys[current["label"]] = key
        return real_iteration_rng(seed, key, iteration)

    monkeypatch.setattr(disintegration, "iteration_rng", spy)

    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]
    loop = s.prepared_loop(name)
    decay = s.config.stems[0].decay
    seed = s.config.seed

    current["label"] = "preview"
    render_window(s, 0.5, stems=[name], reverb=False, master=False)

    current["label"] = "render"
    build_disintegrating_stream(
        loop, loop.n_frames * 3, decay, s.config.output.cycle_crossfade_ms,
        seed, name)

    assert "preview" in keys and "render" in keys, \
        "the spy never observed a call on one of the two paths"
    assert keys["preview"] == keys["render"], (
        f"preview composed rng key {keys['preview']!r} but the render path "
        f"composed {keys['render']!r} for the same stem — preview and "
        "render no longer agree on which noise this repeat plays")


def test_iteration_index_spans_the_arc(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    first, n = preview_iteration_index(s, 0.0)
    last, _ = preview_iteration_index(s, 1.0)
    assert first == 0
    assert last == n - 1
    assert n > 1


def test_soloing_stems_changes_the_result(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    names = s.stem_names()
    assert len(names) >= 2, "the stub provides four distinct stems"
    a = render_window(s, 0.5, stems=names[:1], reverb=False)
    b = render_window(s, 0.5, stems=names, reverb=False)
    assert not np.array_equal(a.data, b.data)


def test_window_is_finite_and_reverb_is_applied(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    dry = render_window(s, 0.5, stems=[name], reverb=False)
    wet = render_window(s, 0.5, stems=[name], reverb=True)
    assert np.all(np.isfinite(wet.data))
    assert not np.array_equal(dry.data, wet.data)


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def test_reverb_does_not_change_the_window_length(tmp_path, stub_separation):
    """The UI plays this buffer on a loop, so it must be exactly one loop long.

    ``effects._predelay`` prepends the pre-delay and both backends return
    ``frames + predelay``, so a naively-reverbed window is longer than the loop
    it came from — which gaps and clicks on every cycle."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]
    dry = render_window(s, 0.5, stems=[name], reverb=False)
    wet = render_window(s, 0.5, stems=[name], reverb=True)
    assert wet.n_frames == dry.n_frames


def test_reverb_window_does_not_open_with_silence(tmp_path, stub_separation):
    """The pre-delay region must be filled, not empty.

    A window that starts with 40ms of nothing is an audible gap once looped."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]
    i, _ = preview_iteration_index(s, 0.5)
    assert i > 0, "this property is only defined where a previous iteration exists"

    wet = render_window(s, 0.5, stems=[name], reverb=True)
    head = int(0.040 * wet.sr)
    assert _rms(wet.data[:head]) > 0.1 * _rms(wet.data)


def test_reverb_window_carries_the_previous_iterations_tail(tmp_path, stub_separation):
    """The pre-delay region is the *previous* iteration bleeding in.

    Trimming alone would already leave the head non-silent (the dry signal is
    there), so the silence test above cannot tell whether the leading context
    is doing anything. This compares against the same window reverbed with no
    context at all — the head must differ, or the bleed isn't happening."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]
    sc = s.config.stems[0]
    i, n = preview_iteration_index(s, 0.5)
    assert i > 0

    chunk = decayed_iteration(
        s.prepared_loop(name), i, n, sc.decay, s.config.seed, name)
    solo = apply_reverb(chunk, s.config.reverb, wet_scale=sc.reverb_send)
    off = reverb_dry_offset(s.config.reverb, chunk.sr)

    wet = render_window(s, 0.5, stems=[name], reverb=True)
    head = int(0.040 * wet.sr)
    assert not np.allclose(
        wet.data[:head], solo.data[off:off + head], atol=1e-6), \
        "the window matches a context-free reverb — no tail is bleeding in"


def test_reverb_window_keeps_the_dry_signal_aligned(tmp_path, stub_separation):
    """The trim must land on this iteration's dry signal, not beside it.

    Cutting at the wrong offset would still yield a full-length, non-silent
    window — it would just be a window of the wrong part of the loop. The dry
    component survives reverb scaled but unshifted, so a wet window and a dry
    one must stay correlated sample-for-sample."""
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    s.config.stems = [StemConfig(name=name)]
    s.config.reverb.wet = 0.0          # dry path only, so alignment is all that is left

    dry = render_window(s, 0.5, stems=[name], reverb=False).data[:, 0]
    wet = render_window(s, 0.5, stems=[name], reverb=True).data[:, 0]
    corr = np.corrcoef(dry, wet)[0, 1]
    assert corr > 0.99, f"dry/wet windows are misaligned (corr={corr:.3f})"


def test_window_is_fast_once_the_session_is_warm(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    render_window(s, 0.5, stems=[name])          # warm the session
    t0 = time.perf_counter()
    render_window(s, 0.6, stems=[name])
    assert time.perf_counter() - t0 < 1.0, "preview must stay interactive"


def test_preview_ignores_stems_the_render_would_drop(tmp_path, stub_separation):
    """A stem in the session but absent from cfg.stems must not be rendered.

    ``_plan_jobs`` falls back to defaults only when *no* configured stem
    matches, so an unlisted stem is dropped by the real render. Previewing it
    would show audio that never ships."""
    s = _session(tmp_path, stub_separation)
    names = s.stem_names()
    assert len(names) >= 2
    s.config.stems = [StemConfig(name=names[0])]
    full = render_window(s, 0.5, reverb=False)
    only = render_window(s, 0.5, stems=[names[0]], reverb=False)
    assert np.array_equal(full.data, only.data)


def test_reverb_send_is_applied_per_stem(tmp_path, stub_separation):
    """Reverb follows each stem's send, as the render does."""
    s = _session(tmp_path, stub_separation)
    names = s.stem_names()[:2]
    s.config.stems = [StemConfig(name=n) for n in names]
    base = render_window(s, 0.5, stems=names, reverb=True)
    s.config.stems[1].reverb_send = 0.0
    changed = render_window(s, 0.5, stems=names, reverb=True)
    assert not np.array_equal(base.data, changed.data)


def _preview_to_render_ratio(tmp_path, stub_separation, cfg, preview_reverb):
    """RMS of a mid-arc mastered preview over the same region of a real render.

    Shared by the two level-matching cases below so they cannot drift apart.
    ``cfg.output.sample_rate`` must equal the working rate: this maps the
    region by frame index, and a resample would shift it."""
    from sleepmix.audio import load_audio
    from sleepmix.disintegration import plan_iterations
    from sleepmix.pipeline import run_pipeline

    song = tmp_path / "s.wav"
    _song(song)
    out = tmp_path / "mix.wav"
    run_pipeline(str(song), cfg, str(out))
    rendered = load_audio(str(out))

    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    assert rendered.sr == loop.sr, "this comparison assumes no resample"
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    n_iter, xfade = plan_iterations(
        loop.n_frames, target_frames, cfg.output.cycle_crossfade_ms, loop.sr)
    stride = max(loop.n_frames - xfade, 1)

    i = max(n_iter // 2, 1)
    progress = i / max(n_iter - 1, 1)
    lo, hi = i * stride + xfade, min((i + 1) * stride, target_frames)
    assert hi > lo, "test setup produced no clean region"

    window = render_window(session, progress, reverb=preview_reverb)   # mastered
    rendered_rms = float(np.sqrt(np.mean(rendered.data[lo:hi] ** 2)))
    window_rms = float(np.sqrt(np.mean(window.data[xfade:xfade + (hi - lo)] ** 2)))
    assert rendered_rms > 0
    return window_rms / rendered_rms


def _level_cfg():
    """The narrowest configuration in which "the preview is at the render's
    level" is a well-posed question.

    Output rate matched to the working rate so nothing resamples, and both
    fades zeroed. The fades are not incidental: ``_apply_fades`` runs *before*
    ``normalize_peak``, so at the default 8 s fade-in the same measurement
    reads −1.82 dB — a real, recorded gap (``docs/project-state.md``), and one
    that has nothing to do with whether the mastering gain is right. Leaving
    them in would make this test fail for a reason it is not about."""
    cfg = MixConfig()
    cfg.output.duration_min = 0.5
    cfg.output.sample_rate = 22050
    cfg.output.fade_in_s = 0.0
    cfg.output.fade_out_s = 0.0
    return cfg


def test_a_mastered_preview_sits_at_the_render_s_level(tmp_path, stub_separation):
    """Preview loudness must track the render's, not float above it.

    This is the check that was missing. The bit-identity test compares
    pre-master, so it passed while previews played ~4 dB hot — and because
    louder reads as less decayed, tuning done in the UI was being done against
    something that would never ship.

    Measured on exactly what ``/api/preview`` sends by default: a stock
    ``MixConfig`` — default reverb, unmodified — previewed with ``reverb=True``.
    The earlier version of this test instead used ``reverb.wet = 0.0`` and a dry
    preview, which measured 0.8692 against a ±1.2 dB bound: 0.15 dB of headroom
    on the one test protecting this branch's central claim, while being far too
    slack to catch a full-dB regression in the path anyone actually uses.

    The bound here is ±2%. The measured value is 1.0003 (+0.00 dB), so that is
    not tight against anything — a preview drifting a quarter of a dB off the
    render fails this, which is roughly where it would start being audible."""
    ratio = _preview_to_render_ratio(
        tmp_path, stub_separation, _level_cfg(), preview_reverb=True)
    assert 0.98 < ratio < 1.02, \
        f"preview is {20 * np.log10(ratio):+.2f} dB off the render (ratio {ratio:.4f})"


def test_a_dry_preview_is_calibrated_against_the_dry_path(tmp_path, stub_separation):
    """``master_gain`` calibrates down whichever path the caller asked for.

    A dry preview has no render to be identical to — every real render reverbs.
    Set ``reverb.wet = 0.0`` and reverb collapses to a flat dry gain, which
    makes the render itself the dry path and the comparison well-posed again.

    Measured: 1.0431, +0.37 dB. That residual is *not* the mastering gain — it
    is the inter-iteration ``equal_power_crossfade``, which sums two decayed
    iterations and can exceed either one's peak, so ``normalize_peak`` scales
    the whole render slightly further down than a single-window calibration
    predicts. Setting ``cycle_crossfade_ms = 0.0`` and changing nothing else
    moves this measurement to 0.9995. Hence the ±5% bound: it is the size of a
    known, separately-recorded effect, not slack chosen to fit.

    Before per-flag calibration this same case read 0.6922 (−3.20 dB), because
    the factor was always measured with reverb on and applied regardless."""
    cfg = _level_cfg()
    cfg.reverb.wet = 0.0
    ratio = _preview_to_render_ratio(
        tmp_path, stub_separation, cfg, preview_reverb=False)
    assert 0.95 < ratio < 1.05, \
        f"dry preview is {20 * np.log10(ratio):+.2f} dB off (ratio {ratio:.4f})"


def test_master_gain_is_computed_once_per_config(tmp_path, stub_separation):
    """It costs a window render, so it must not run on every preview."""
    from sleepmix.preview import master_gain

    s = _session(tmp_path, stub_separation)
    first = master_gain(s)
    assert s.master_gain[True] == first
    assert master_gain(s) == s.master_gain[True]

    changed = MixConfig()
    changed.output.duration_min = 2.0
    changed.tempo.speed = 0.5
    s.update_config(changed)
    assert s.master_gain == {}, "a config change must invalidate the gain"


def test_master_gain_survives_an_empty_stems_list(tmp_path, stub_separation):
    """``MixConfig.from_dict({"stems": []})`` is a supported state —
    ``plan_stem_configs`` documents it explicitly, falling back to every
    available stem at defaults — and ``render_window(..., master=False)``
    already handles it. ``cfg.stems[0].decay``, read directly rather than
    through ``plan_stem_configs``, does not: it raised a bare ``IndexError``
    with no message, reachable as a 500 from ``POST /api/preview`` (that
    endpoint catches ``ValueError``, not ``IndexError``). At the parent
    commit — before ``master_gain`` read ``cfg.stems`` at all — this same
    call returned a number."""
    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig.from_dict({"stems": []})
    cfg.output.duration_min = 2.0
    session = RenderSession(str(song), cfg, separate_fn=stub_separation)

    from sleepmix.preview import master_gain
    gain = master_gain(session)
    assert gain > 0 and np.isfinite(gain)


def test_master_gain_is_calibrated_per_signal_path(tmp_path, stub_separation):
    """A dry preview must not be mastered with a wet-calibrated factor.

    Reverb changes the peak the calibration window measures, so one factor
    cannot serve both paths — applying the wet one to a dry window put it
    3.2 dB low, which reads as more decayed than it is."""
    from sleepmix.preview import master_gain
    from sleepmix.util import db_to_amp

    s = _session(tmp_path, stub_separation)
    wet = master_gain(s, reverb=True)
    dry = master_gain(s, reverb=False)
    assert set(s.master_gain) == {True, False}
    assert wet != dry, "the two paths cannot share one calibration"

    # Each factor puts its own path's loudest window at the configured peak.
    target = db_to_amp(s.config.output.peak_db)
    for flag in (True, False):
        peak = float(np.abs(render_window(s, 0.0, reverb=flag).data).max())
        assert abs(peak - target) < 1e-4, f"reverb={flag} peaks at {peak}"


def test_master_gain_matches_the_old_formula_when_nothing_overlaps(tmp_path, stub_separation):
    """The property that keeps every level-matching test above honest.

    ``_session``'s config uses the default (zero-gap) arrangement, so no two
    placements ever sound together: the densest frame has exactly one
    placement, the density ratio is exactly 1.0, and ``master_gain`` must
    come out bit-identical to the old "measure iteration 0 alone" formula it
    replaces. If the arrangement-aware rewrite had changed anything in this
    case, every test above — all of which run at zero gap — would have been
    silently measuring a different thing."""
    from sleepmix.preview import master_gain
    from sleepmix.util import db_to_amp

    s = _session(tmp_path, stub_separation)
    gain = master_gain(s, reverb=True)

    loudest = render_window(s, 0.0, reverb=True, master=False)
    peak = float(np.abs(loudest.data).max())
    target = db_to_amp(s.config.output.peak_db)
    assert gain == target / peak


def test_a_rising_amplitude_arc_still_calibrates_on_the_first_repeat(
        tmp_path, stub_separation):
    """One slider drag used to put the preview 3.85 dB above the render.

    ``amp_start_db`` and ``amp_end_db`` are independent sliders over the same
    −60…0 range, so ``amp_start_db < amp_end_db`` — the stem *growing* across
    the arc rather than fading — is a state the mixer can reach from stock
    settings in one drag. The arrangement here is the default one: zero gap,
    nothing overlapping, so this is not about stacking at all.

    ``arrangement.decay_amplitude_proxy`` used to report the first repeat as
    the quietest on such an arc, because it applied ``amp_start_db`` at
    progress 0 where ``apply_decay`` applies nothing. ``densest_frame`` then
    picked the *last* placement and ``master_gain`` calibrated against a
    window from the far end of the arc — measured here as a mastered dry
    preview peaking at 1.3883 against the render's 0.8913 normalisation.

    So: with no overlap, the gain must still be exactly the old
    "measure the first repeat alone" formula, whichever way the arc runs."""
    import pytest

    from sleepmix.preview import master_gain
    from sleepmix.util import db_to_amp

    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    for sc in cfg.stems:
        sc.decay.amp_start_db = -30.0
        sc.decay.amp_end_db = -16.0
    s = RenderSession(str(song), cfg, separate_fn=stub_separation)

    gain = master_gain(s, reverb=False)
    first = render_window(s, 0.0, reverb=False, master=False)
    peak = float(np.abs(first.data).max())
    target = db_to_amp(cfg.output.peak_db)
    assert gain == target / peak

    mastered = float(np.abs(render_window(s, 0.0, reverb=False).data).max())
    assert mastered == pytest.approx(target, abs=1e-4), (
        f"a rising arc mastered the first window to {mastered:.4f}, "
        f"{20 * np.log10(mastered / target):+.2f} dB off the render's target")


def test_master_gain_accounts_for_concurrent_repeats(tmp_path, stub_separation):
    """The regression this task fixes, checked against the corrected formula
    directly rather than against a full render — ``_preview_to_render_ratio``
    assumes a uniform, gap-blind stride and cannot be reused for an
    overlapping arrangement without asserting something else by accident.

    A negative gap makes several near-fresh repeats sound together at the
    densest frame. The old code measured iteration 0 alone and would have
    left the render's true peak above target; the fix scales that single
    window's measured peak up by the density ratio before deriving the gain,
    so the resulting gain must be smaller than what the old, overlap-blind
    measurement would have produced."""
    import pytest

    from sleepmix.arrangement import (
        SegmentInfo, concurrent_placements, densest_frame, plan_arrangement,
        xfade_frames)
    from sleepmix.config import plan_stem_configs
    from sleepmix.preview import master_gain
    from sleepmix.util import db_to_amp, lerp, shape_progress

    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    cfg.arrangement.gap_start_s = -3.0
    cfg.arrangement.gap_end_s = -3.0
    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    name = session.stem_names()[0]
    loop = session.prepared_loop(name)
    target_frames = int(cfg.output.duration_min * 60 * loop.sr)
    plan = plan_arrangement(
        [SegmentInfo("mix", 0, loop.n_frames)], cfg, target_frames, loop.sr)
    decay = plan_stem_configs(session.stem_names(), cfg)[0].decay
    xfade = xfade_frames(cfg.output.cycle_crossfade_ms, loop.n_frames, loop.sr)
    frame = densest_frame(plan, decay, xfade)
    here = concurrent_placements(plan, frame, xfade)
    assert len(here) >= 2, \
        "test setup produced no overlap; assertions below would be vacuous"

    dominant = min(here, key=lambda p: p.decay_progress)

    # The density ratio, recomputed from the decay *settings* rather than by
    # calling the two functions under test. That circularity used to be the
    # whole weakness of this test: it called ``concurrent_amplitude`` and
    # ``decay_amplitude_proxy`` to build the number it then asserted
    # ``master_gain`` had computed with those same two functions, so any
    # change to either moved both sides together and the equality held
    # regardless. Reverting root-sum-square to a plain sum — a one-line
    # mutation reinstating a measured +17.7 dB error — left this test green.
    # Written out here, that mutation fails it. ``lerp`` and
    # ``shape_progress`` are still called: they are not what this pins down,
    # and re-deriving an ``exp`` curve by hand would only add a second place
    # to get the curve wrong.
    def amp(p):
        # Mirrors apply_decay's short-circuit, as decay_amplitude_proxy does.
        if p <= 0:
            return 1.0
        return 10 ** (lerp(decay.amp_start_db, decay.amp_end_db,
                           shape_progress(p, decay.curve)) / 20.0)

    single = amp(dominant.decay_progress)
    total = sum(amp(p.decay_progress) ** 2 for p in here) ** 0.5
    ratio = total / single
    assert ratio > 1.0, "overlap should raise the density ratio above 1"

    loudest = render_window(
        session, dominant.decay_progress, reverb=False, master=False)
    peak = float(np.abs(loudest.data).max())
    target = db_to_amp(cfg.output.peak_db)
    expected_gain = target / (peak * ratio)

    gain = master_gain(session, reverb=False)
    assert gain == pytest.approx(expected_gain, rel=1e-9)

    naive_peak = float(
        np.abs(render_window(session, 0.0, reverb=False, master=False).data).max())
    naive_gain = target / naive_peak
    assert gain < naive_gain, \
        "overlap must pull the gain down from the old iteration-0-only measurement"


def test_mastering_preserves_the_arc(tmp_path, stub_separation):
    """One factor for all windows — not per-window normalization.

    If each window were normalized to its own peak, every point in the decay
    arc would come back equally loud and the whole effect would be inaudible in
    preview."""
    s = _session(tmp_path, stub_separation)
    early = render_window(s, 0.0, reverb=False)
    late = render_window(s, 1.0, reverb=False)
    assert float(np.abs(late.data).max()) < float(np.abs(early.data).max())


def test_all_stems_off_refuses_rather_than_rendering_the_default_mix(
        tmp_path, stub_separation):
    """The failure this whole check exists for, asserted on the audio.

    Before the split in ``plan_stem_configs``, a config with every stem
    switched off fell through to "every available stem at defaults" — so the
    preview came back as the *full default mix* at full level (measured rms
    0.194 against the default's 0.298, i.e. audible music, not silence), with
    every gain, reverb send and decay curve the user had tuned discarded in the
    same step. Reachable in four clicks from the mixer's Enabled checkboxes.

    So: the default mix is genuinely loud, and asking for nothing does not
    return it — or anything else."""
    import pytest

    from sleepmix.config import NothingToRender

    s = _session(tmp_path, stub_separation)
    default = render_window(s, 0.5, reverb=False)
    assert float(np.sqrt(np.mean(default.data ** 2))) > 1e-3

    off = MixConfig()
    off.output.duration_min = 2.0
    off.stems = [StemConfig(name=name, enabled=False) for name in s.stem_names()]
    s.update_config(off)

    with pytest.raises(NothingToRender, match="switched off"):
        render_window(s, 0.5, reverb=False)


def _with_bed(cfg, enabled=True):
    """A copy of cfg with the bed switched on and given something audible."""
    import copy
    out = copy.deepcopy(cfg)
    out.soundbed.enabled = enabled
    out.soundbed.noise_gain_db = -12.0
    return out


def test_a_preview_includes_the_sound_bed(tmp_path, stub_separation):
    """The gap this closes: enabling pink noise used to change nothing you
    could hear in the mixer, which is a difference in character rather than
    level — and character is the judgement a preview exists to support."""
    song = tmp_path / "s.wav"
    _song(song)
    quiet = RenderSession(str(song), _with_bed(_level_cfg(), enabled=False),
                          separate_fn=stub_separation)
    loud = RenderSession(str(song), _with_bed(_level_cfg(), enabled=True),
                         separate_fn=stub_separation)
    without = render_window(quiet, 0.5, master=False)
    with_bed = render_window(loud, 0.5, master=False)
    assert with_bed.data.shape == without.data.shape
    assert not np.allclose(with_bed.data, without.data)


def test_the_bed_is_the_same_every_time_it_is_rendered(tmp_path, stub_separation):
    """Derived from the seed rather than freshly random, so the memoised master
    gain cannot depend on which draw happened to occur."""
    song = tmp_path / "s.wav"
    _song(song)
    session = RenderSession(str(song), _with_bed(_level_cfg()),
                            separate_fn=stub_separation)
    first = render_window(session, 0.5, master=False)
    second = render_window(session, 0.5, master=False)
    assert np.array_equal(first.data, second.data)


def test_a_soloed_preview_leaves_the_bed_out(tmp_path, stub_separation):
    """Solo already does not match the render, which has every enabled stem.
    A bed over an isolated stem masks the thing it was isolated to hear."""
    song = tmp_path / "s.wav"
    _song(song)
    session = RenderSession(str(song), _with_bed(_level_cfg()),
                            separate_fn=stub_separation)
    plain = RenderSession(str(song), _with_bed(_level_cfg(), enabled=False),
                          separate_fn=stub_separation)
    name = session.stem_names()[0]
    one = render_window(session, 0.5, stems=[name], master=False)
    same = render_window(plain, 0.5, stems=[name], master=False)
    assert np.array_equal(one.data, same.data)


def test_the_preview_indexes_the_repeats_the_render_actually_produces(
        tmp_path, stub_separation):
    """With a gap, the render has fewer repeats. The preview must agree, or
    scrubbing to the end auditions an iteration that does not exist.

    ``duration_min=0.5`` is chosen, not incidental: at this song/gap
    combination it makes ``plan_iterations`` (gap-blind) report 5 while
    ``plan_arrangement`` (gap-aware) produces 4 placements — the two
    disagree, so the assertions below can actually fail. A smaller duration
    puts the target inside a single loop and both would agree by accident;
    see the sibling caution in the task brief."""
    from sleepmix.arrangement import SegmentInfo, plan_arrangement

    song = tmp_path / "s.wav"
    _song(song)
    cfg = MixConfig()
    cfg.output.duration_min = 0.5
    cfg.arrangement.gap_start_s = 2.0
    cfg.arrangement.gap_end_s = 2.0

    session = RenderSession(str(song), cfg, separate_fn=stub_separation)
    loop = session.prepared_loop(session.stem_names()[0])
    target = int(cfg.output.duration_min * 60 * loop.sr)
    plan = plan_arrangement(
        [SegmentInfo("mix", 0, loop.n_frames)], cfg, target, loop.sr)
    assert len(plan.placements) > 1, \
        "test setup produced a single-placement plan; assertions below would be vacuous"

    _, n_iter = preview_iteration_index(session, 0.0)
    assert n_iter == len(plan.placements)

    last, _ = preview_iteration_index(session, 1.0)
    assert last == len(plan.placements) - 1


def test_soloing_a_stem_the_render_would_drop_refuses(tmp_path, stub_separation):
    """Solo a stem, then switch it off — the mixer's own reachable order.

    This used to return a one-frame WAV behind a 200: a well-formed file that
    plays silence and says nothing about why."""
    import pytest

    from sleepmix.config import NothingToRender

    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]

    cfg = MixConfig()
    cfg.output.duration_min = 2.0
    cfg.stems = [StemConfig(name=n, enabled=(n != name)) for n in s.stem_names()]
    s.update_config(cfg)

    with pytest.raises(NothingToRender, match=name):
        render_window(s, 0.5, stems=[name], reverb=False)
