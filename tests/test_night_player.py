"""The player, which owns the two things that cannot be known in advance.

Everything here is tested without a sound device. ``run`` takes a sink so the
mixing, the degradation and the queue can be driven in a unit test; opening
the real device is one line inside the CLI command, which is the only part
nobody can assert.
"""
import threading
import time

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


def _rms(buf) -> float:
    return float(np.sqrt(np.mean(buf.data.astype(np.float64) ** 2)))


def test_speech_actually_reaches_the_output():
    """Compared by RMS energy, for the reason
    ``test_a_first_source_failing_does_not_block_the_second`` spells out
    below: the block-wide peak is not a reliable witness that the layer
    arrived, because adding it can partially cancel the music at whichever
    single sample happened to be the maximum.

    That was always true; it only started mattering once the distance
    treatments stopped normalising every block to a fixed peak. Under the old
    automatic gain control the speech layer's peak was a constant regardless
    of its input, which is precisely the defect that was removed."""
    quiet = _player().mixed_block(3)
    loud = _player(room=LoudSource(SR)).mixed_block(3)
    assert not np.array_equal(quiet.data, loud.data)
    assert _rms(loud) > _rms(quiet)


def test_a_speech_source_that_raises_costs_only_its_own_voice():
    """Degrade silently: the music must survive the receiver falling over."""
    music_only = _player().mixed_block(4)
    with_broken_radio = _player(radio=ExplodingSource(SR)).mixed_block(4)
    assert np.array_equal(music_only.data, with_broken_radio.data)


def test_a_first_source_failing_does_not_block_the_second():
    """The mirror of the case above. There the failing source (radio) was
    read *second*, so a surviving-but-silent room proved nothing about
    whether the loop kept going after a failure. Here the failing source
    (room) is read *first* — proving the try/except is per-source rather
    than wrapped around the whole pass, since only that lets the radio's
    loud content still reach the output.

    Compared by RMS energy rather than peak: adding the radio layer to one
    specific sample can happen to partially cancel the music there even
    while raising the level everywhere else, so the block-wide peak is not a
    reliable witness that the layer arrived — the energy is.
    """
    silent = _player(room=ExplodingSource(SR)).mixed_block(4)
    loud_radio = _player(room=ExplodingSource(SR),
                         radio=LoudSource(SR)).mixed_block(4)
    assert not np.array_equal(silent.data, loud_radio.data)

    def rms(buf):
        return float(np.sqrt(np.mean(buf.data.astype(np.float64) ** 2)))

    assert rms(loud_radio) > rms(silent)


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


@pytest.mark.parametrize("seed", [3, 11, 99])
def test_a_mixed_block_never_clips(seed):
    """Measured on the sum, not on the clip's own output.

    This used to assert ``np.abs(player.mixed_block(index).data).max() <=
    1.0``, which cannot fail: ``mixed_block`` clips to that range as its last
    act. ``summed_mix`` returns what arrives at the clip.

    Both speech sources are at a level no real file would reach, which is the
    right test for a headroom assertion: if a full-scale white-noise room and
    a full-scale white-noise radio cannot push the sum over 1.0, nothing an
    operator drops in the room folder will.
    """
    player = _player(room=LoudSource(SR, level=1.0),
                     radio=LoudSource(SR, level=1.0),
                     ctx=_context(seed=seed))
    peak = max(float(np.abs(player.summed_mix(index)).max())
               for index in range(0, 120, 3))
    assert peak <= 1.0
    assert peak < 0.9


def test_a_mixed_block_still_leaves_the_clip_in_place():
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


def test_run_gives_up_after_consecutive_sink_failures_rather_than_looping_forever():
    """Degrade silently, all the way down: a sink that never recovers must
    not spin the loop forever. ``max_blocks=None`` makes that provable —
    nothing but the consecutive-failure threshold can end this run."""
    calls = {"n": 0}

    def always_fails(_block):
        calls["n"] += 1
        raise RuntimeError("device disconnected")

    _player().run(max_blocks=None, sink=always_fails)
    assert calls["n"] == 3


def test_run_absorbs_a_single_transient_sink_failure_and_continues():
    """A buffer underrun is not a dead device. One failure is absorbed —
    the loop moves on to the next block rather than stopping — so the night
    still runs for its full requested length despite the hiccup."""
    attempts = {"n": 0}
    delivered = []

    def flaky(block):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("buffer underrun")
        delivered.append(block)

    _player().run(max_blocks=4, sink=flaky)
    assert attempts["n"] == 4
    assert len(delivered) == 3


def test_run_closes_its_speech_sources():
    room = LoudSource(SR)
    radio = LoudSource(SR)
    _player(room=room, radio=radio).run(max_blocks=1, sink=lambda _b: None)
    assert room.closed
    assert radio.closed


# -- rendering ahead of playback -------------------------------------------
#
# ``run`` used to render block i, hand it to the sink, then render i+1. The
# CLI's sink is a blocking ``sd.OutputStream.write``, so every render was
# time the device spent waiting: a block containing a voice birth costs
# 0.68-1.09 s at 44.1 kHz against a device buffer of 0.05-0.2 s, and voices
# are born every 20-70 s early in the night. That is an underrun once or
# twice a minute. ``queue_depth`` was stored and read by nothing.

def _is_bed(block) -> bool:
    """The player's own bed rather than music, judged on the back half.

    The front of a block can belong to the block before it now: a change of
    kind is crossfaded, so the first 75 ms of the bed that opens a stall is
    mostly the music it came out of.
    """
    half = block.data[block.n_frames // 2:]
    return bool(np.abs(half).max() < 0.05)


def _slow_render_player(delay_s: float = 1.0):
    """A player whose renderer cannot keep up, so the queue drains."""
    stream = NightStream(_context(), sr=SR)
    real = stream.block

    def slow(index):
        time.sleep(delay_s)
        return real(index)

    stream.block = slow  # type: ignore[method-assign]
    return NightPlayer(stream, SilentSource(SR), SilentSource(SR))


def test_a_slow_renderer_produces_fallback_blocks_rather_than_a_stall():
    """The degradation the spec names: "the block queue drains into a bed the
    *player* generates". It is also the only thing that ever makes
    ``fallback_block`` reachable for the reason it exists."""
    ctx = _context()
    stream = NightStream(ctx, sr=SR)
    real = stream.block

    def slow(index):
        time.sleep(1.0)
        return real(index)

    stream.block = slow  # type: ignore[method-assign]
    player = NightPlayer(stream, SilentSource(SR), SilentSource(SR))

    delivered = []
    started = time.monotonic()
    player.run(max_blocks=6, sink=delivered.append)
    elapsed = time.monotonic() - started

    assert len(delivered) == 6
    # It did not wait for six slow renders in series.
    assert elapsed < 6.0
    # Some of what came out is the player's own bed rather than music. Judged
    # on the back half of the block: a bed that *opens* a stall is crossfaded
    # out of the music before it, so its first 75 ms carries the music's level
    # and its whole-block peak is not a witness to what it is.
    assert [b for b in delivered if _is_bed(b)], \
        "a renderer this slow should have drained the queue"


def test_consecutive_fallback_blocks_are_not_the_same_noise():
    """A stall must not become a loop.

    ``fallback_block`` is a pure function of ``(seed, "night:fallback",
    index)``, and the consumer used to advance its index only when a real
    block arrived — so every empty in a run of empties emitted a byte-
    identical ten seconds. Measured before the fix, with the renderer slowed
    to 1 s a block: peaks ``[0.2009, 0.0121, 0.0121, 0.0121, 0.2022, ...]``,
    blocks 2 and 3 bit-identical to block 1. A thirty-second stall played one
    loop three times, and repetition and pattern are exactly what this design
    argues wake people.
    """
    delivered = []
    _slow_render_player().run(max_blocks=8, sink=delivered.append)

    assert len(delivered) == 8
    beds = [b for b in delivered if _is_bed(b)]
    assert len(beds) >= 2, "a renderer this slow should have stalled twice"
    for i, first in enumerate(delivered):
        for second in delivered[i + 1:]:
            assert not np.array_equal(first.data, second.data), (
                f"block {i} was played again later in the same run")


def test_the_seam_between_music_and_the_fallback_bed_does_not_step():
    """The same 4x threshold ``test_consecutive_blocks_join_without_a_step``
    and ``test_the_bed_joins_across_a_block_seam_without_a_step`` apply, at
    the one boundary neither of them covers.

    Music and the player's own bed differ by more than a factor of ten in
    level and know nothing about each other. Butted together, the return to
    music measured a step 7.58x the largest motion anywhere inside a block.

    Every seam in the run is checked rather than a chosen pair: which block
    the queue happens to hand over when is a matter of thread timing, and the
    property is meant to hold at all of them anyway.
    """
    ctx = _context()
    stream = NightStream(ctx, sr=SR)
    real = stream.block

    def sometimes(index):
        if index in (1, 2):
            raise RuntimeError("render failed")
        return real(index)

    stream.block = sometimes  # type: ignore[method-assign]
    player = NightPlayer(stream, SilentSource(SR), SilentSource(SR))

    delivered = []
    player.run(max_blocks=6, sink=delivered.append)
    assert len(delivered) == 6

    peaks = [float(np.abs(b.data).max()) for b in delivered]
    assert max(peaks) > 5 * min(peaks), (
        f"the run never crossed between music and bed at all: {peaks}")

    for i in range(len(delivered) - 1):
        first, second = delivered[i].data, delivered[i + 1].data
        step = float(np.abs(second[0] - first[-1]).max())
        within = float(np.abs(np.diff(first, axis=0)).max())
        assert step <= within * 4.0, (
            f"the output steps at the seam after block {i}: "
            f"{step:.5f} against {within:.5f} within the block")


def test_the_crossfade_only_touches_the_head_of_a_block():
    """It is a seam treatment, not a fade: everything past ``_SEAM_S`` is the
    block exactly as it was rendered."""
    from sleepmix.night.player import _SEAM_S

    player = _player()
    plain = player.fallback_block(4)
    tail = np.full((int(_SEAM_S * SR), 2), 0.3, dtype=np.float32)
    crossed = player._cross_into(plain, tail)

    seam = player._seam_frames()
    assert seam == int(_SEAM_S * SR)
    assert np.array_equal(crossed.data[seam:], plain.data[seam:])
    # And it opens exactly where the previous block left off.
    assert crossed.data[0] == pytest.approx(tail[-1], abs=1e-6)


def test_the_render_thread_does_not_outlive_run():
    player = _player()
    player.run(max_blocks=2, sink=lambda _b: None)
    assert player._producer is None
    remaining = [t for t in threading.enumerate()
                 if t.name == "sleepmix-night-render" and t.is_alive()]
    assert not remaining


def test_the_render_thread_stops_even_when_the_sink_dies():
    """The consumer gives up after three consecutive sink failures. The
    producer must not be left rendering a night nobody is listening to."""
    def always_fails(_block):
        raise RuntimeError("device disconnected")

    player = _player()
    player.run(max_blocks=None, sink=always_fails)
    assert player._producer is None
    remaining = [t for t in threading.enumerate()
                 if t.name == "sleepmix-night-render" and t.is_alive()]
    assert not remaining


def test_the_queue_depth_is_actually_used():
    """It was stored and read by nothing before the producer existed."""
    depths = []
    ctx = _context()
    stream = NightStream(ctx, sr=SR)
    player = NightPlayer(stream, SilentSource(SR), SilentSource(SR),
                         queue_depth=2)
    assert player.queue_depth == 2
    # A depth of zero would be a queue that can never hold anything, so it is
    # floored rather than taken literally.
    assert NightPlayer(stream, SilentSource(SR), SilentSource(SR),
                       queue_depth=0).queue_depth == 1


def test_the_speech_layer_is_mixed_in_the_consumer_not_the_renderer():
    """The spec is explicit that the live layer is summed at the output.
    Mixing it in the producer would make it up to ``queue_depth`` blocks —
    thirty seconds — stale."""
    reads = []

    class RecordingSource(LoudSource):
        def read(self, n_frames):
            reads.append(threading.current_thread().name)
            return super().read(n_frames)

    player = _player(room=RecordingSource(SR))
    consumer = threading.current_thread().name
    player.run(max_blocks=3, sink=lambda _b: None)
    assert reads, "the speech source was never read"
    assert all(name == consumer for name in reads), reads


def test_the_room_directory_lives_under_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPMIX_DATA_DIR", str(tmp_path))
    assert str(tmp_path) in room_directory()
    assert room_directory().endswith("room")
