"""The generators, and the one rule they may not break.

No transients. Every voice must arrive and leave over seconds, because an
attack is an event and events wake people up. That is asserted directly here
rather than left to listening, since it is the property most likely to be
broken by an innocent-looking change to either generator.
"""
import numpy as np
import pytest

from sleepmix.config import StemDecayConfig
from sleepmix.night.palette import FADE_S, render_voice
from sleepmix.night.plan import Voice

SR = 22050


def _voice(texture: str = "drone", index: int = 0, seconds: float = 60.0,
           pitch_hz: float = 110.0) -> Voice:
    return Voice(index=index, birth_frame=0, n_frames=int(seconds * SR),
                 pitch_hz=pitch_hz, texture=texture, decay=StemDecayConfig())


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_stereo_and_the_length_it_says_it_is(texture):
    voice = _voice(texture)
    buf = render_voice(voice, SR, seed=1)
    assert buf.n_frames == voice.n_frames
    assert buf.n_channels == 2
    assert buf.sr == SR


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_attack(texture):
    """The first moments must be far quieter than the middle."""
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    opening = x[:int(0.05 * SR)].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert opening < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_has_no_release_cliff(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    closing = x[-int(0.05 * SR):].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert closing < middle * 0.05


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_a_voice_is_reproducible(texture):
    a = render_voice(_voice(texture), SR, seed=5)
    b = render_voice(_voice(texture), SR, seed=5)
    assert np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_different_voices_draw_different_noise(texture):
    a = render_voice(_voice(texture, index=0), SR, seed=5)
    b = render_voice(_voice(texture, index=1), SR, seed=5)
    assert not np.array_equal(a.data, b.data)


@pytest.mark.parametrize("texture", ["drone", "noiseband"])
def test_nothing_clips(texture):
    buf = render_voice(_voice(texture), SR, seed=1)
    assert np.abs(buf.data).max() <= 1.0


def test_a_drone_sits_at_the_pitch_it_was_asked_for():
    voice = _voice("drone", pitch_hz=110.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    # Look at the sustained middle, away from the fades.
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 110.0) < 3.0


def test_a_noiseband_is_centred_near_its_pitch_and_is_not_a_tone():
    voice = _voice("noiseband", pitch_hz=220.0, seconds=20.0)
    buf = render_voice(voice, SR, seed=1)
    mono = buf.data.mean(axis=1)
    window = mono[5 * SR: 15 * SR]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
    peak_hz = freqs[int(np.argmax(spectrum))]
    assert abs(peak_hz - 220.0) < 60.0
    # A tone puts nearly all its energy in one bin; a band does not.
    assert spectrum.max() / spectrum.sum() < 0.05


def test_a_voice_shorter_than_two_fades_still_fades_both_ends():
    voice = _voice("drone", seconds=FADE_S)
    buf = render_voice(voice, SR, seed=1)
    x = np.abs(buf.data).max(axis=1)
    assert x[0] < 1e-4
    assert x[-1] < 1e-4
    assert x.max() > 1e-3


def test_an_unknown_texture_is_refused():
    with pytest.raises(ValueError, match="unknown texture"):
        render_voice(_voice("trumpet"), SR, seed=1)
