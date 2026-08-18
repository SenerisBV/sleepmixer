"""The squelch, the static, and a network that is allowed to fail.

The reason radio is worth the trouble is that it gates itself: HF is already
transmissions separated by silence and static, so the sparseness that makes
YALT work does not have to be simulated by a timer. These tests are mostly
about that gate behaving like a squelch rather than like a noise gate on a
vocal — it must let the static through underneath, because the static is the
part the operator specifically asked for.
"""
import time

import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night import speech as speech_mod
from sleepmix.night.speech import (
    RadioSource, SilentSource, over_the_air, radio_source_from, squelch,
)

SR = 22050


def _wait_for_audio(source: RadioSource, n_frames: int,
                    timeout: float = 5.0) -> np.ndarray | None:
    """The first read that carries something, or None.

    The feed now fills a ring buffer on its own thread, so ``read`` answers
    immediately with whatever has arrived — which, microseconds after the
    source is constructed, is nothing. Polling is what a non-blocking source
    asks of a test; it does not weaken what is being asserted.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buf = source.read(n_frames)
        assert buf.n_frames == n_frames
        if np.abs(buf.data).max() > 0.0:
            return buf.data
        time.sleep(0.01)
    return None


def _transmission_over_static(sr=SR):
    """Two seconds of static with a loud burst in the middle second."""
    rng = np.random.default_rng(1)
    x = rng.standard_normal(2 * sr).astype(np.float32) * 0.02
    t = np.arange(sr) / sr
    x[sr // 2: sr // 2 + sr] += (0.4 * np.sin(2 * np.pi * 600 * t)
                                 ).astype(np.float32)
    return x


def test_the_squelch_opens_on_a_transmission_and_closes_after_it():
    x = _transmission_over_static()
    gate = squelch(x, SR, floor_rms=0.02)
    during = gate[SR: SR + SR // 2].mean()
    between = gate[: SR // 4].mean()
    assert during > 0.8
    assert between < 0.2


def test_the_squelch_envelope_is_smooth():
    """A gate that snaps is a click, and a click wakes people."""
    gate = squelch(_transmission_over_static(), SR, floor_rms=0.02)
    assert np.abs(np.diff(gate)).max() < 0.01


def test_the_squelch_stays_in_range():
    gate = squelch(_transmission_over_static(), SR, floor_rms=0.02)
    assert gate.min() >= 0.0
    assert gate.max() <= 1.0


def test_the_gate_is_not_forced_shut_at_the_ends_of_a_block():
    """Both filter passes start settled, not from zero.

    Run with the default zero initial conditions, ``gate[:5]`` and
    ``gate[-5:]`` were exactly 0 regardless of what was on the air. The
    player calls this once per ten-second block, so that was a ~100 ms duck
    repeating at 0.1 Hz all night, and a transmission straddling a seam
    chopped at both ends.
    """
    sr = SR
    t = np.arange(2 * sr) / sr
    # A transmission that is already in progress when the block opens and
    # still in progress when it closes.
    x = (0.4 * np.sin(2 * np.pi * 600 * t)).astype(np.float32)
    gate = squelch(x, sr, floor_rms=0.02)
    assert gate[:5].min() > 0.8
    assert gate[-5:].min() > 0.8


def test_a_transmission_across_a_seam_is_not_chopped():
    """The same signal split into two blocks must gate the same as one."""
    sr = SR
    t = np.arange(2 * sr) / sr
    x = (0.4 * np.sin(2 * np.pi * 600 * t)).astype(np.float32)
    whole = squelch(x, sr, floor_rms=0.02)
    halves = np.concatenate([squelch(x[:sr], sr, floor_rms=0.02),
                             squelch(x[sr:], sr, floor_rms=0.02)])
    assert np.abs(whole - halves).max() < 0.05


def test_pure_static_never_opens_the_gate():
    rng = np.random.default_rng(2)
    x = (rng.standard_normal(2 * SR) * 0.02).astype(np.float32)
    assert squelch(x, SR, floor_rms=0.02).mean() < 0.2


def test_over_the_air_keeps_the_static_underneath_the_gate():
    """The static is the point, not a side effect to be gated away."""
    buf = AudioBuffer(np.stack([_transmission_over_static()] * 2, axis=1), SR)
    out = over_the_air(buf, intelligibility=0.8, static_gain=0.25)
    quiet_part = np.abs(out.data[: SR // 4]).max()
    assert quiet_part > 0.0


def test_over_the_air_is_band_limited():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((SR, 2)).astype(np.float32) * 0.3
    out = over_the_air(AudioBuffer(x, SR), intelligibility=0.8,
                       static_gain=0.2)
    spectrum = np.abs(np.fft.rfft(out.data.mean(axis=1))) ** 2
    freqs = np.fft.rfftfreq(out.n_frames, 1.0 / SR)
    above = spectrum[freqs > 4000.0].sum() / max(spectrum.sum(), 1e-12)
    below = spectrum[freqs < 200.0].sum() / max(spectrum.sum(), 1e-12)
    assert above < 0.02
    assert below < 0.05


def test_lower_intelligibility_is_quieter():
    buf = AudioBuffer(np.stack([_transmission_over_static()] * 2, axis=1), SR)
    clear = over_the_air(buf, 0.8, 0.2)
    murky = over_the_air(buf, 0.05, 0.2)
    assert np.abs(murky.data).max() < np.abs(clear.data).max()


def test_over_the_air_passes_level_through_rather_than_normalising_it():
    """The quiet between transmissions is the point, not a level to remove.

    The treatment used to end in ``blended * (target / peak)``, so the
    inter-transmission static was lifted to the same peak as the
    transmissions — and the gain was recomputed per block, so it stepped at
    every seam.
    """
    x = np.stack([_transmission_over_static()] * 2, axis=1)
    loud = AudioBuffer(x, SR)
    quiet = AudioBuffer(x * 0.001, SR)
    loud_out = np.abs(over_the_air(loud, 0.8, 0.2).data).max()
    quiet_out = np.abs(over_the_air(quiet, 0.8, 0.2).data).max()
    assert quiet_out == pytest.approx(loud_out * 0.001, rel=0.05)


def test_over_the_airs_gain_does_not_depend_on_the_block_it_is_given():
    x = np.stack([_transmission_over_static()] * 2, axis=1).copy()
    x[len(x) // 2:] *= 0.1
    first = over_the_air(AudioBuffer(x[:len(x) // 2], SR), 0.5, 0.2)
    second = over_the_air(AudioBuffer(x[len(x) // 2:], SR), 0.5, 0.2)
    ratio = np.abs(second.data).max() / np.abs(first.data).max()
    assert ratio == pytest.approx(0.1, rel=0.25)


def test_over_the_air_preserves_length():
    buf = AudioBuffer(np.zeros((5000, 2), dtype=np.float32), SR)
    assert over_the_air(buf, 0.5, 0.2).n_frames == 5000


def test_a_radio_source_that_cannot_connect_reads_as_silence(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(speech_mod, "_open_stream", refuse)
    source = RadioSource("http://example.invalid/stream", SR)
    buf = source.read(4000)
    assert buf.n_frames == 4000
    assert np.all(buf.data == 0.0)


def test_a_radio_source_that_dies_mid_night_goes_silent_once_it_drains(
        monkeypatch):
    """A dead feed costs its own voice and nothing else.

    The assertion has one more step in it than it used to, and the extra step
    is the point of the ring buffer: what already arrived is still played out
    after the connection dies, and only then does the layer go quiet. Reads
    keep answering the whole way through, and none of them raises.
    """
    class DyingStream:
        def __init__(self):
            self.calls = 0

        def read(self, n_frames):
            self.calls += 1
            if self.calls > 1:
                raise OSError("stream dropped")
            return np.full((n_frames, 2), 0.1, dtype=np.float32)

        def close(self):
            return None

    monkeypatch.setattr(speech_mod, "_open_stream",
                        lambda *a, **k: DyingStream())
    source = RadioSource("http://example.invalid/stream", SR, chunk_s=0.1,
                         buffer_s=1.0)
    try:
        assert _wait_for_audio(source, 1000) is not None

        for _ in range(500):
            buf = source.read(1000)
            assert buf.n_frames == 1000
            if not np.any(buf.data):
                break
        else:
            pytest.fail("the ring never drained after the feed died")

        # And it stays silent rather than reconnecting or raising.
        for _ in range(5):
            assert np.all(source.read(1000).data == 0.0)
    finally:
        source.close()


def test_a_radio_read_answers_immediately_rather_than_waiting_for_the_network(
        monkeypatch):
    """``read`` is called from the playback path, where the deadline is the
    length of a device buffer. It used to block until ten seconds of live
    stream had arrived, bounded only by ``requests``' 10 s timeout."""
    class SlowStream:
        def read(self, n_frames):
            time.sleep(0.5)
            return np.full((n_frames, 2), 0.1, dtype=np.float32)

        def close(self):
            return None

    monkeypatch.setattr(speech_mod, "_open_stream",
                        lambda *a, **k: SlowStream())
    source = RadioSource("http://example.invalid/stream", SR, chunk_s=1.0)
    try:
        started = time.monotonic()
        buf = source.read(SR * 10)
        elapsed = time.monotonic() - started
        assert buf.n_frames == SR * 10
        assert elapsed < 0.2
        # What was not there yet is zeros, not a stall and not a raise.
        assert np.all(np.isfinite(buf.data))
    finally:
        source.close()


def test_a_radio_source_stops_its_thread_when_closed(monkeypatch):
    class ForeverStream:
        def read(self, n_frames):
            time.sleep(0.01)
            return np.zeros((n_frames, 2), dtype=np.float32)

        def close(self):
            return None

    monkeypatch.setattr(speech_mod, "_open_stream",
                        lambda *a, **k: ForeverStream())
    source = RadioSource("http://example.invalid/stream", SR, chunk_s=0.1)
    source.read(100)
    thread = source._thread
    assert thread is not None and thread.daemon
    source.close()
    thread.join(timeout=5.0)
    assert not thread.is_alive()
    assert np.all(source.read(100).data == 0.0)


def test_radio_source_from_none_is_silent():
    assert isinstance(radio_source_from(None, SR), SilentSource)


def test_radio_source_from_empty_string_is_silent():
    assert isinstance(radio_source_from("", SR), SilentSource)
