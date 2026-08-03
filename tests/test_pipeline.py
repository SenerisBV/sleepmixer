"""End-to-end render through the fallbacks (no ML deps required)."""
import numpy as np
import pytest

import sleepmix.separation
from sleepmix.audio import AudioBuffer, load_audio, save_audio
from sleepmix.config import MixConfig
from sleepmix.pipeline import run_pipeline
from sleepmix.progress import CancelToken, Cancelled, ProgressReporter


def _synth_song(path, sr=22050, secs=6.0):
    """A simple chord + melody so there's something to loop and separate."""
    t = np.arange(int(sr * secs)) / sr
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330))
    melody = 0.5 * np.sin(2 * np.pi * (440 + 40 * np.sin(2 * np.pi * 0.5 * t)) * t)
    y = (chord + melody) / 4.0
    stereo = np.stack([y, y], axis=1).astype(np.float32)
    save_audio(AudioBuffer(stereo, sr), str(path))


def test_full_render_fallback(tmp_path, monkeypatch):
    """A full render on a machine with no working Demucs.

    Making Demucs *fail* is the point, and it is why this test does not simply
    take the ``stub_separation`` fixture like every other render test here. The
    stub returns four clean stems, which is the success path — it would leave
    the name of this test a lie in the other direction and exercise none of the
    degradation this asserts: ``separation.separate``'s ``except`` branch, the
    single-``mix``-stem substitution, and ``plan_stem_configs``' all-or-nothing
    fallback (the default config names vocals/other/bass/drums, none of which
    exist here, so every one of them must be discarded in favour of one default
    ``StemConfig`` for ``mix``).

    Patching ``_demucs_separate`` rather than skipping separation also keeps
    the suite honest about its own claim to run without ML dependencies: this
    used to invoke real Demucs on any machine that had it, at ~10s a run.
    """
    def no_demucs(*_a, **_k):
        raise RuntimeError("demucs unavailable (simulated)")

    monkeypatch.setattr(sleepmix.separation, "_demucs_separate", no_demucs)

    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.25      # 15 s render to keep the test fast
    cfg.output.sample_rate = 22050
    cfg.soundbed.enabled = True
    cfg.soundbed.binaural_enabled = True

    lines = []
    with pytest.warns(UserWarning, match="Demucs separation unavailable"):
        run_pipeline(str(song), cfg, str(out), progress=lines.append)

    # The whole track arrived as one 'mix' stem, and stem planning fell back to
    # defaults for it instead of dropping everything.
    assert any("Processing stem 'mix'…" == line for line in lines), lines
    assert not any("vocals" in line for line in lines), lines

    rendered = load_audio(str(out))
    assert rendered.n_channels == 2
    assert abs(rendered.duration - 15.0) < 1.0
    assert np.all(np.isfinite(rendered.data))
    # Mastered peak should respect the configured ceiling (-1 dBFS).
    assert np.max(np.abs(rendered.data)) <= 10 ** (-1.0 / 20.0) + 1e-3


def test_reporter_receives_ordered_monotonic_events(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    seen = []
    run_pipeline(str(song), cfg, str(out), reporter=ProgressReporter(seen.append))

    stages = [e.stage for e in seen]
    assert stages[0] == "separate"
    assert stages[-1] == "master"
    assert "stem" in stages
    fractions = [e.fraction for e in seen]
    assert fractions == sorted(fractions), "progress must never go backwards"
    assert 0.0 <= fractions[0] and fractions[-1] <= 1.0


def test_cancel_aborts_the_render(tmp_path, stub_separation):
    """Cancellation lands inside the per-iteration loop, not before it.

    Cancelling on the *first* event trips the post-separation check in
    ``run_pipeline`` before any stem is touched, so it never reaches the check
    inside ``build_disintegrating_stream`` — which is the one a cancellable UI
    render actually depends on, since that is where a long render spends its
    time. Waiting for a ``stem`` event puts the cancel where it matters:
    ``_process_stem`` is already running when the token flips.

    Asserting only that ``Cancelled`` is raised does not pin that down.
    ``run_pipeline`` checks the token again before mastering, so a render whose
    per-iteration check had been deleted outright would still raise here — just
    later, after grinding through every iteration of every stem first. Checked
    by deleting that line: the raise moves to ``run_pipeline`` and only the
    traceback assertion below notices.
    """
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    token = CancelToken()
    reporter = ProgressReporter(
        lambda e: token.cancel() if e.stage == "stem" else None)

    with pytest.raises(Cancelled) as excinfo:
        run_pipeline(str(song), cfg, str(out), reporter=reporter, cancel=token)

    raised_in = [entry.name for entry in excinfo.traceback]
    assert "build_disintegrating_stream" in raised_in, (
        "cancellation did not reach the per-iteration check; it was absorbed by "
        f"an earlier or later one. Traceback: {raised_in}")

    assert not out.exists(), "a cancelled render must not leave output behind"


def test_string_progress_callback_still_works(tmp_path, stub_separation):
    song = tmp_path / "song.wav"
    out = tmp_path / "mix.wav"
    _synth_song(song)

    cfg = MixConfig()
    cfg.output.duration_min = 0.1
    cfg.output.sample_rate = 22050

    lines = []
    run_pipeline(str(song), cfg, str(out), progress=lines.append)

    assert any("Separating" in line for line in lines)
    assert any("Wrote" in line for line in lines)
