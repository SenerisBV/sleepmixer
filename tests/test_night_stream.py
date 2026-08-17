"""Blocks, and the guarantee the whole architecture rests on.

Block N rendered on its own must be bit-identical to block N rendered after
its predecessors. If that ever stops holding, block independence was a hope
rather than a property — and the most likely cause is something live having
been routed into this module, which is exactly what the last test here forbids.
"""
import numpy as np
import pytest

from sleepmix.night.context import NightContext, Weather
from sleepmix.night.stream import BLOCK_S, NightStream

SR = 22050


def _context(seed: int = 3, length_s: float = 8 * 3600.0) -> NightContext:
    return NightContext(
        seed=seed, night_length_s=length_s,
        weather=Weather(cloud_cover=0.5, precipitation_mm=0.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)


def _stream(**kwargs) -> NightStream:
    return NightStream(_context(**kwargs), sr=SR)


def test_a_block_is_the_length_and_shape_it_should_be():
    stream = _stream()
    block = stream.block(0)
    assert block.n_frames == int(BLOCK_S * SR)
    assert block.n_channels == 2
    assert block.sr == SR


def test_a_block_rendered_alone_matches_one_rendered_in_sequence():
    """The invariant, asserted numerically rather than argued."""
    target = 37
    alone = NightStream(_context(), sr=SR).block(target)

    sequential = NightStream(_context(), sr=SR)
    for index in range(target + 1):
        produced = sequential.block(index)
    assert np.array_equal(alone.data, produced.data)


def test_far_apart_blocks_are_independent_too():
    """A block deep into the night must not need the seven hours before it."""
    deep = int(6 * 3600 / BLOCK_S)
    alone = NightStream(_context(), sr=SR).block(deep)
    again = NightStream(_context(), sr=SR).block(deep)
    assert np.array_equal(alone.data, again.data)


def test_blocks_are_reproducible_from_the_seed():
    a = NightStream(_context(seed=11), sr=SR).block(5)
    b = NightStream(_context(seed=11), sr=SR).block(5)
    assert np.array_equal(a.data, b.data)


def test_a_different_seed_gives_different_audio():
    a = NightStream(_context(seed=11), sr=SR).block(5)
    b = NightStream(_context(seed=12), sr=SR).block(5)
    assert not np.array_equal(a.data, b.data)


def test_nothing_clips():
    stream = _stream()
    for index in (0, 3, 40, 400):
        assert np.abs(stream.block(index).data).max() <= 1.0


def test_the_late_night_is_quieter_than_the_early_night():
    stream = _stream()
    early = np.sqrt(np.mean(stream.block(6).data ** 2))
    late = np.sqrt(np.mean(stream.block(int(7 * 3600 / BLOCK_S)).data ** 2))
    assert late < early


def test_consecutive_blocks_join_without_a_step():
    """A discontinuity at a block seam is a click, and a click wakes people."""
    stream = _stream()
    first, second = stream.block(12), stream.block(13)
    step = np.abs(second.data[0] - first.data[-1]).max()
    within = np.abs(np.diff(first.data, axis=0)).max()
    assert step <= within * 4.0


def test_a_block_past_the_end_of_the_night_still_renders():
    """The arc clamps rather than ending, so the stream never runs out."""
    stream = _stream()
    block = stream.block(int(20 * 3600 / BLOCK_S))
    assert block.n_frames == int(BLOCK_S * SR)


def test_the_voice_cache_does_not_grow_without_bound():
    stream = _stream()
    for index in range(300):
        stream.block(index)
    assert len(stream._cache) <= 24


def test_the_stream_never_touches_a_speech_source():
    """Nothing live may enter the deterministic layer."""
    import sleepmix.night.stream as stream_module
    source = open(stream_module.__file__).read()
    assert "speech" not in source.lower()
