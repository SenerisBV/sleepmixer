"""The squelch, the static, and a network that is allowed to fail.

The reason radio is worth the trouble is that it gates itself: HF is already
transmissions separated by silence and static, so the sparseness that makes
YALT work does not have to be simulated by a timer. These tests are mostly
about that gate behaving like a squelch rather than like a noise gate on a
vocal — it must let the static through underneath, because the static is the
part the operator specifically asked for.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night import speech as speech_mod
from sleepmix.night.speech import (
    RadioSource, SilentSource, over_the_air, radio_source_from, squelch,
)

SR = 22050


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


def test_a_radio_source_that_dies_mid_night_reads_as_silence(monkeypatch):
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

    monkeypatch.setattr(speech_mod, "_open_stream", lambda *a, **k: DyingStream())
    source = RadioSource("http://example.invalid/stream", SR)
    assert np.abs(source.read(1000).data).max() > 0.0
    second = source.read(1000)
    assert second.n_frames == 1000
    assert np.all(second.data == 0.0)


def test_radio_source_from_none_is_silent():
    assert isinstance(radio_source_from(None, SR), SilentSource)


def test_radio_source_from_empty_string_is_silent():
    assert isinstance(radio_source_from("", SR), SilentSource)
