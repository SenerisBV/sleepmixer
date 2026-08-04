import time

import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig, StemConfig
from sleepmix.disintegration import decayed_iteration, plan_iterations
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
