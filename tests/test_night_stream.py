"""Blocks, and the guarantee the whole architecture rests on.

Block N rendered on its own must be bit-identical to block N rendered after
its predecessors. If that ever stops holding, block independence was a hope
rather than a property — and the most likely cause is something live having
been routed into this module, which is exactly what the last test here forbids.
"""
from pathlib import Path

import numpy as np
import pytest

from sleepmix.config import SoundbedConfig
from sleepmix.night.context import NightContext, Weather
from sleepmix.night.plan import plan_voices
from sleepmix.night.stream import BLOCK_S, NightStream

from .import_guard import forbidden_imports

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


@pytest.mark.parametrize("seed", [3, 11, 42, 99])
def test_nothing_clips(seed):
    """Measured on the sum, not on the clip's own output.

    This test used to read ``np.abs(stream.block(index).data).max() <= 1.0``,
    which is a tautology: the last statement of ``block`` is
    ``np.clip(..., -1, 1)``. It passed while seed 99 was summing to 1.27 and
    clipping 9 of its first 120 blocks. ``summed`` exists so that the number
    arriving at the clip is the number under assertion.

    The first 120 blocks are the worst case on purpose — the arc's level
    ceiling is at its highest and its density is at its densest there, so a
    night that does not clip in its first twenty minutes does not clip.
    """
    # With the bed on, because that is what ``sleepmix night`` ships.
    stream = NightStream(_context(seed=seed), sr=SR,
                         bed=SoundbedConfig(enabled=True))
    peak = max(float(np.abs(stream.summed(index)).max())
               for index in range(120))
    assert peak <= 1.0
    # And with margin, so that an ordinary change of taste in the palette
    # does not silently start clipping again.
    assert peak < 0.9


def test_the_clip_is_a_guard_and_not_a_level_control():
    """``block`` still clips, and what it hands out is still in range."""
    stream = _stream()
    for index in (0, 3, 40, 400):
        assert np.abs(stream.block(index).data).max() <= 1.0


def test_a_rendered_voice_still_has_no_attack_after_the_whole_chain():
    """The composition test the palette's own no-attack test cannot be.

    ``tests/test_night_palette.py`` asserts that ``render_voice`` fades in and
    out, and it passes — but two stages run after it. ``apply_decay`` mixes
    its noise floor in *last*, after the lowpass and after the gain, so a
    voice's first sample stepped from exact digital silence to broadband hiss
    in one sample no matter how carefully the generator faded. Then the
    reverb tail ends wherever the padding ends. This tests the buffer that is
    actually sliced into blocks.
    """
    stream = _stream()
    voices = plan_voices(stream.ctx, stream.sr, 0, stream.block_frames)
    assert voices
    rendered = stream._rendered(voices[0])

    x = np.abs(rendered.data).max(axis=1)
    opening = x[:int(0.05 * SR)].max()
    closing = x[-int(0.05 * SR):].max()
    middle = x[len(x) // 2 - SR: len(x) // 2 + SR].max()
    assert middle > 0.0
    assert opening < middle * 0.05
    assert closing < middle * 0.05


def test_a_voice_born_late_carries_less_hiss_than_one_born_early():
    """The decay engine's noise floor descends with the arc.

    Left at ``StemDecayConfig``'s -42 dB default it was an absolute level the
    arc could not touch, so a voice born at hour six carried exactly as much
    broadband hiss as one born at hour zero — under a brightness ceiling and
    a level ceiling that had both come down by then.
    """
    from sleepmix.night.clock import arc_at
    from sleepmix.night.plan import NOISE_BELOW_LEVEL_DB, _decay_for
    from sleepmix.config import StemDecayConfig

    ctx = _context()
    early = _decay_for(arc_at(0.0, ctx), StemDecayConfig())
    late = _decay_for(arc_at(6 * 3600.0, ctx), StemDecayConfig())
    assert late.noise_end_db < early.noise_end_db - 10.0
    assert early.noise_end_db == arc_at(0.0, ctx).level_db + NOISE_BELOW_LEVEL_DB
    # And it sits well under the tone it is meant to be underneath.
    assert early.noise_end_db < early.amp_end_db - 30.0


def test_one_bad_voice_costs_only_itself():
    """Degradation is per voice, not per block.

    Any exception inside ``_rendered`` used to propagate out of ``block``, so
    the player replaced the whole ten seconds with its fallback bed — pink
    noise where music was. The spec asks for "a voice raises → skip it, log
    it, continue."
    """
    stream = _stream()

    def voices_in(i):
        return plan_voices(stream.ctx, stream.sr,
                           max(i * stream.block_frames - int(6.0 * SR), 0),
                           (i + 1) * stream.block_frames)

    index = next(i for i in range(200) if len(voices_in(i)) >= 2)
    voices = voices_in(index)
    healthy = stream.block(index)
    assert np.abs(healthy.data).max() > 0.0

    broken = NightStream(_context(), sr=SR)
    doomed = voices[0].index
    real = broken._rendered

    def explode(voice):
        if voice.index == doomed:
            raise RuntimeError("this voice fell over")
        return real(voice)

    broken._rendered = explode  # type: ignore[method-assign]
    thinner = broken.block(index)

    # The block still exists, still has music in it, and is not the fallback
    # bed — it is the same block minus one voice.
    assert np.abs(thinner.data).max() > 0.0
    assert not np.array_equal(thinner.data, healthy.data)


def test_a_block_of_nothing_but_broken_voices_is_silence_not_an_exception():
    stream = NightStream(_context(), sr=SR)

    def explode(voice):
        raise RuntimeError("every voice fell over")

    stream._rendered = explode  # type: ignore[method-assign]
    block = stream.block(4)
    assert block.n_frames == int(BLOCK_S * SR)
    assert np.all(np.isfinite(block.data))


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


# -- the sound bed ---------------------------------------------------------
#
# ``sleepmix night`` turns the bed on; ``SoundbedConfig``'s own default stays
# off. Until it was turned on, the arc-driven bed darkening below was
# unreachable and untested, and a shipped night was mostly digital silence:
# at 6.5 h in, 26 of 30 consecutive blocks measured as exact zeros, with
# voice-coverage gaps of up to 694 s.

def _bedded(seed: int = 3) -> NightStream:
    return NightStream(_context(seed=seed), sr=SR,
                       bed=SoundbedConfig(enabled=True))


def _centroid_hz(x: np.ndarray, sr: int) -> float:
    mono = x.mean(axis=1) if x.ndim == 2 else x
    power = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    return float((power * freqs).sum() / max(power.sum(), 1e-20))


def test_the_bed_is_off_unless_it_is_asked_for():
    """The default is what every other caller in the codebase relies on."""
    assert np.all(_stream()._bed(5) == 0.0)


def test_the_bed_is_there_when_it_is_asked_for():
    assert np.abs(_bedded()._bed(5)).max() > 0.0


def test_the_bed_darkens_as_the_night_goes_on():
    """The arc governs the bed's spectrum, not only its level.

    Late in the night the voices are dim and sparse, so an unfiltered bed
    would be most of what is left — and the mix would get *brighter* in
    character exactly when the arc wants it darkest.
    """
    stream = _bedded()
    early = _centroid_hz(stream._bed(6), SR)
    mid = _centroid_hz(stream._bed(int(4 * 3600 / BLOCK_S)), SR)
    late = _centroid_hz(stream._bed(int(7 * 3600 / BLOCK_S)), SR)
    assert mid < early
    assert late < mid
    assert late < early / 3.0


def test_the_beds_level_descends_too():
    stream = _bedded()

    def rms(i):
        return float(np.sqrt(np.mean(stream._bed(i).astype(np.float64) ** 2)))

    early = rms(6)
    mid = rms(int(4 * 3600 / BLOCK_S))
    late = rms(int(7 * 3600 / BLOCK_S))
    assert mid < early
    assert late < mid


def test_a_wetter_night_has_more_bed():
    """"Cloud and rain -> the noise bed's level and character" is a steering
    row, and until the bed was switched on it had nothing to act on."""
    def rms(ctx):
        stream = NightStream(ctx, sr=SR, bed=SoundbedConfig(enabled=True))
        return float(np.sqrt(np.mean(stream._bed(6).astype(np.float64) ** 2)))

    dry = _context()
    wet = NightContext(
        seed=dry.seed, night_length_s=dry.night_length_s,
        weather=Weather(cloud_cover=1.0, precipitation_mm=8.0, wind_ms=3.0,
                        pressure_hpa=1013.25, pressure_trend_hpa=0.0),
        moon_phase=0.5, day_length_h=12.0)
    assert rms(wet) > rms(dry)


def test_the_bed_joins_across_a_block_seam_without_a_step():
    """Independent noise per block is inaudible while the noise is broadband
    and audible the moment the arc darkens it: lowpassing collapses the
    within-block motion and leaves the seam standing. Measured at 44.1 kHz
    mid-night before the fix, the step was 7.3x the largest step inside a
    block; the same 4x threshold the music's own seam test uses.

    (The circular convolution in ``_soft_lowpass`` was suspected and is not
    the cause. The figure once quoted here, -41 dB relative to the block
    peak, was wrong: re-measured against a linearly-convolved reference with
    the pink noise the bed actually generates, the wrap reaches -17.3 dB at a
    500 Hz cutoff and -16.2 dB at 3000 Hz. It is still confined to the
    window's first and last samples — above -60 dB only within 1.6 ms of
    either edge, interior matching to -71.7 dB — and those are the samples
    the crossfade below multiplies by approximately zero. The seam was the
    noise, not the filter; see ``stream._bed``.)
    """
    stream = _bedded()
    for index in (6, int(4 * 3600 / BLOCK_S), int(7 * 3600 / BLOCK_S)):
        first, second = stream._bed(index), stream._bed(index + 1)
        step = np.abs(second[0] - first[-1]).max()
        within = np.abs(np.diff(first, axis=0)).max()
        assert step <= within * 4.0, f"bed steps at the seam after block {index}"


def test_a_bedded_block_is_still_block_independent():
    """The overlap-add reaches back a block. It must not reach back a night."""
    target = 37
    alone = _bedded().block(target)
    sequential = _bedded()
    for index in range(target + 1):
        produced = sequential.block(index)
    assert np.array_equal(alone.data, produced.data)


def test_a_bedded_night_is_never_digitally_silent():
    """The reason the bed is switched on at all.

    Without it, 26 of 30 consecutive blocks at 6.5 h in were exact zeros.
    """
    stream = _bedded()
    start = int(6.5 * 3600 / BLOCK_S)
    for index in range(start, start + 30):
        assert np.abs(stream.block(index).data).max() > 0.0


def test_a_block_past_the_end_of_the_night_still_renders():
    """The arc clamps rather than ending, so the stream never runs out."""
    stream = _stream()
    block = stream.block(int(20 * 3600 / BLOCK_S))
    assert block.n_frames == int(BLOCK_S * SR)


def _cache_bytes_held(stream: NightStream) -> int:
    return sum(buf.data.nbytes for buf in stream._cache.values())


def test_the_voice_cache_does_not_grow_without_bound():
    """Bounded by bytes, which is the bound the code actually keeps.

    Both cache tests used to assert ``len(_cache) <= 24`` — a number that
    stopped corresponding to anything when the cache moved from an entry
    ceiling to a byte ceiling, and that a 256 MB cache satisfies trivially at
    the test suite's sample rate. Worse, nothing asserted the byte bound at
    all: deleting ``self._cache_bytes -= evicted.data.nbytes`` from
    ``_rendered`` would let the running total climb forever, collapse the
    cache to a single entry, and thrash — and every test would still pass.
    """
    from sleepmix.night.stream import _CACHE_BYTES

    stream = _stream()
    for index in range(300):
        stream.block(index)

    # The bound the eviction loop is written against.
    assert stream._cache_bytes <= _CACHE_BYTES
    # The running total is what it claims to be. This is the assertion that
    # fails if the subtraction on eviction is ever lost.
    assert stream._cache_bytes == _cache_bytes_held(stream)
    # And it is a cache rather than a single slot being thrashed: several
    # voices overlap at any moment and all of them stay resident.
    assert len(stream._cache) > 1


def test_a_voice_evicted_from_the_cache_still_renders_the_same():
    """Eviction is invisible to correctness: cache size is not part of the contract."""
    from sleepmix.night.stream import _CACHE_BYTES

    stream = _stream()
    first = stream.block(0)

    born_at_zero = {v.index for v in
                    plan_voices(stream.ctx, stream.sr, 0, stream.block_frames)}
    assert born_at_zero  # sanity: block 0 always has at least one voice

    for index in range(1, 400):
        stream.block(index)
    assert stream._cache_bytes <= _CACHE_BYTES
    assert stream._cache_bytes == _cache_bytes_held(stream)
    # Confirm eviction actually happened for block 0's voices, rather than
    # merely hoping it did.
    assert not (born_at_zero & set(stream._cache))

    again = stream.block(0)
    assert np.array_equal(first.data, again.data)


def test_the_stream_never_touches_a_speech_source():
    """Nothing live may enter the deterministic layer."""
    import sleepmix.night.stream as stream_module
    stream_path = Path(stream_module.__file__)
    repo_root = stream_path.parent.parent.parent  # sleepmix/night/stream.py -> root

    violations = forbidden_imports(
        stream_path, repo_root, {"sleepmix.night.speech"})
    assert not violations, (
        f"stream.py imports the speech layer: {violations}. The speech layer "
        "is mixed at playback, not here — that is what makes block "
        "independence testable at all."
    )
