"""The player, which owns the two things that cannot be known in advance.

Everything here is tested without a sound device. ``run`` takes a sink so the
mixing, the degradation and the queue can be driven in a unit test; opening
the real device is one line inside the CLI command, which is the only part
nobody can assert.
"""
import numpy as np
import pytest

from sleepmix.audio import AudioBuffer
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.player import NightPlayer, room_directory
from sleepmix.night.speech import SilentSource
from sleepmix.night.stream import BLOCK_S, NightStream

SR = 22050


def _context(seed: int = 3) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=8 * 3600.0,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)


class LoudSource:
    """A speech source that always has something to say."""

    def __init__(self, sr: int, level: float = 0.5) -> None:
        self.sr = sr
        self.level = level
        self.closed = False

    def read(self, n_frames: int) -> AudioBuffer:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((n_frames, 2)).astype(np.float32) * self.level
        return AudioBuffer(x, self.sr)

    def close(self) -> None:
        self.closed = True


class ExplodingSource:
    def __init__(self, sr: int) -> None:
        self.sr = sr

    def read(self, n_frames: int) -> AudioBuffer:
        raise RuntimeError("the receiver fell over")

    def close(self) -> None:
        return None


def _player(room=None, radio=None, ctx=None) -> NightPlayer:
    ctx = ctx or _context()
    stream = NightStream(ctx, sr=SR)
    return NightPlayer(stream,
                       room or SilentSource(SR),
                       radio or SilentSource(SR))


def test_a_mixed_block_is_the_right_shape():
    block = _player().mixed_block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    assert block.n_channels == 2


def test_speech_actually_reaches_the_output():
    quiet = _player().mixed_block(3)
    loud = _player(room=LoudSource(SR)).mixed_block(3)
    assert not np.array_equal(quiet.data, loud.data)
    assert np.abs(loud.data).max() > np.abs(quiet.data).max()


def test_a_speech_source_that_raises_costs_only_its_own_voice():
    """Degrade silently: the music must survive the receiver falling over."""
    music_only = _player().mixed_block(4)
    with_broken_radio = _player(radio=ExplodingSource(SR)).mixed_block(4)
    assert np.array_equal(music_only.data, with_broken_radio.data)


def test_both_speech_sources_failing_still_produces_music():
    block = _player(room=ExplodingSource(SR),
                    radio=ExplodingSource(SR)).mixed_block(4)
    assert np.abs(block.data).max() > 0.0


def test_speech_gets_quieter_as_the_night_goes_on():
    """The intelligibility ceiling is read at mix time, so the two layers
    descend together rather than the music alone."""
    player = _player(room=LoudSource(SR))
    n = int(BLOCK_S * SR)
    early = np.abs(player._speech(6, n)).max()
    late = np.abs(player._speech(int(7 * 3600 / BLOCK_S), n)).max()
    assert late < early


def test_a_mixed_block_never_clips():
    player = _player(room=LoudSource(SR, level=1.0),
                     radio=LoudSource(SR, level=1.0))
    for index in (0, 5, 200):
        assert np.abs(player.mixed_block(index).data).max() <= 1.0


def test_the_fallback_block_is_quiet_noise_not_silence():
    """When the renderer cannot keep up, the player makes its own bed."""
    block = _player().fallback_block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    peak = np.abs(block.data).max()
    assert 0.0 < peak < 0.2


def test_run_delivers_the_blocks_it_was_asked_for():
    delivered = []
    _player().run(max_blocks=4, sink=delivered.append)
    assert len(delivered) == 4
    assert all(b.n_frames == int(BLOCK_S * SR) for b in delivered)


def test_run_falls_back_rather_than_stopping_when_rendering_fails():
    ctx = _context()
    stream = NightStream(ctx, sr=SR)
    broken = {"count": 0}

    def explode(index):
        broken["count"] += 1
        raise RuntimeError("render failed")

    stream.block = explode  # type: ignore[method-assign]
    player = NightPlayer(stream, SilentSource(SR), SilentSource(SR))

    delivered = []
    player.run(max_blocks=3, sink=delivered.append)
    assert len(delivered) == 3
    assert broken["count"] == 3
    assert all(np.abs(b.data).max() < 0.2 for b in delivered)


def test_run_closes_its_speech_sources():
    room = LoudSource(SR)
    _player(room=room).run(max_blocks=1, sink=lambda _b: None)
    assert room.closed


def test_the_room_directory_lives_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert str(tmp_path) in room_directory()
    assert room_directory().endswith("room")
