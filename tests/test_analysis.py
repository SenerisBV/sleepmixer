import numpy as np

from sleepmix.analysis import find_loop
from sleepmix.audio import AudioBuffer
from sleepmix.config import LoopConfig


def _tone(secs=10.0, sr=22050):
    t = np.arange(int(sr * secs)) / sr
    y = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def test_explicit_loop_points_are_used_verbatim():
    buf = _tone()
    cfg = LoopConfig(start_s=2.0, end_s=6.0)
    lp = find_loop(buf, cfg)
    assert lp.start == int(2.0 * buf.sr)
    assert lp.end == int(6.0 * buf.sr)


def test_explicit_loop_points_are_clamped_to_the_buffer():
    buf = _tone(secs=5.0)
    cfg = LoopConfig(start_s=-1.0, end_s=99.0)
    lp = find_loop(buf, cfg)
    assert lp.start == 0
    assert lp.end == buf.n_frames


def test_loop_points_past_the_end_fall_back_to_auto():
    """Clamping must not manufacture a one-frame loop."""
    buf = _tone(secs=10.0)
    lp = find_loop(buf, LoopConfig(start_s=999.0, end_s=1000.0))
    auto = find_loop(buf, LoopConfig())
    assert (lp.start, lp.end) == (auto.start, auto.end)


def test_degenerate_explicit_range_falls_back_to_auto():
    buf = _tone(secs=10.0)
    lp = find_loop(buf, LoopConfig(start_s=5.0, end_s=5.01))  # 10 ms
    auto = find_loop(buf, LoopConfig())
    assert (lp.start, lp.end) == (auto.start, auto.end)


def test_omitting_loop_points_still_auto_detects():
    buf = _tone()
    lp = find_loop(buf, LoopConfig())
    assert lp.end > lp.start
    assert lp.tempo > 0


def test_partial_loop_points_fall_back_to_auto():
    buf = _tone()
    lp = find_loop(buf, LoopConfig(start_s=2.0))  # end_s omitted
    auto = find_loop(buf, LoopConfig())
    assert (lp.start, lp.end) == (auto.start, auto.end)
