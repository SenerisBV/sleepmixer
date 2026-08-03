import time

import numpy as np

from sleepmix.audio import AudioBuffer, save_audio
from sleepmix.config import MixConfig, StemConfig
from sleepmix.disintegration import decayed_iteration
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
    out = render_window(s, progress, stems=[name], reverb=False)
    i, n = preview_iteration_index(s, progress)
    expected = decayed_iteration(
        s.prepared_loop(name), i, n, s.config.stems[0].decay, s.config.seed, name)
    assert np.array_equal(out.data, expected.data)


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


def test_window_is_fast_once_the_session_is_warm(tmp_path, stub_separation):
    s = _session(tmp_path, stub_separation)
    name = s.stem_names()[0]
    render_window(s, 0.5, stems=[name])          # warm the session
    t0 = time.perf_counter()
    render_window(s, 0.6, stems=[name])
    assert time.perf_counter() - t0 < 1.0, "preview must stay interactive"
