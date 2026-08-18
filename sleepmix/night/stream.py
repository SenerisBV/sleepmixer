"""Block assembly: the deterministic half of the night, entire.

Nothing live reaches this module and nothing live may be added to it. That is
the boundary the design's central invariant is drawn at — a block of *music*
rendered in isolation is bit-identical to the same block rendered in sequence —
and it is only checkable because the speech layer is mixed at playback instead
of here.

**A voice is rendered once, whole, and then sliced.** Blocks are seconds and
voices are minutes, so every voice spans several blocks. Teaching the decay
engine to render part of a placement would mean changing the contract at the
heart of this codebase; rendering the voice complete and slicing it costs a
bounded amount of memory (see ``_CACHE_BYTES`` — a single voice is tens of
megabytes, not the whole cache) and changes nothing. It also solves the
reverb problem for
free: reverb is applied to the *whole* voice before it is cached, so the tail
lives inside the cached buffer and survives being sliced. No block is ever
reverbed, so no reverb tail is ever cut off at a seam.

**A voice is decayed at ``progress = 1.0``, and the arc supplies the
endpoints.** ``plan.py`` builds each voice's ``StemDecayConfig`` with
``lowpass_end_hz`` and ``amp_end_db`` set from the ceilings at its birth, so
applying the decay fully puts the voice exactly where the night permits. The
descent across the night comes from successive voices being built under lower
ceilings — not from any voice decaying within itself.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

import numpy as np

from ..audio import AudioBuffer
from ..config import ReverbConfig, SoundbedConfig
from ..disintegration import apply_decay
from ..effects import apply_reverb, reverb_dry_offset
from ..soundbed import colored_noise
from ..util import db_to_amp, iteration_rng
from .clock import arc_at
from .context import NightContext
from .palette import fade_envelope, render_voice
from .plan import Voice, plan_voices

_log = logging.getLogger(__name__)

BLOCK_S = 10.0

# How much rendered audio to keep, in bytes.
#
# The cache used to be bounded by *entries* — 24 of them, on the reasoning that
# a voice is a few megabytes. It is not. At 44.1 kHz a voice averages 52.7 MB
# and peaks at 86.6 MB (four minutes, stereo, float32, plus a six-second reverb
# tail), so 24 entries is 1.27 GB typical and 2.08 GB worst case, held resident
# for eight hours. At most about eight voices are ever alive at one moment, so
# the entry count was buying nothing that the byte ceiling does not.
#
# Bounding by bytes also makes the cache behave the same way at every sample
# rate, which an entry count does not: the 22.05 kHz test suite was holding
# half as much as a real night for the same number of entries.
_CACHE_BYTES = 256 * 1024 * 1024

# Reverb tail kept past a voice's death, so the room does not stop with it.
_TAIL_S = 6.0

# The bed's level is scaled by the arc alongside everything else, and pushed
# further by weather: a wet night sounds wet.
_BED_BASE_DB = -34.0
_BED_RAIN_BOOST_DB = 6.0

# How much each bed window runs past the end of its own block, so the next
# block has something to fade out of. See ``NightStream._bed``.
_BED_OVERLAP_S = 0.25


def _soft_lowpass(x: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    """Roll ``x`` off above ``cutoff_hz``, gently and without ringing.

    Shapes the spectrum directly rather than running an IIR filter, the same
    approach ``palette._noise_band`` uses — a resonant filter rung by noise is
    an easy way to produce a whistle, and a whistle at 3 AM is the opposite of
    the point.
    """
    n = len(x)
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    shape = 1.0 / (1.0 + (freqs / max(cutoff_hz, 1.0)) ** 2)
    return np.fft.irfft(spectrum * shape, n=n).astype(np.float32)


class NightStream:
    """The music layer, addressable one block at a time.

    ``block(i)`` is a pure function of ``(ctx, sr, block_s, i)``. The cache is
    an optimisation and is never allowed to be an input: evicting it changes
    nothing about what comes out. The tests check that two ways — rendering
    the same block from two different instances, and rendering an early block
    again from one instance after its voices have certainly been evicted from
    that instance's own cache.

    Prepared-source profiles arrive on ``ctx.sources`` rather than as a
    constructor argument, for exactly this reason: a profile that lived on
    the instance instead would still be part of what ``block(i)`` reads, but
    it would no longer be visible in the signature that the independence
    argument is stated against. Keeping it on ``ctx`` means ``block(i)``
    stays a pure function of ``(ctx, sr, block_s, i)`` with no amendment, and
    the independence proof carries over to a night with sources in play
    unchanged.
    """

    def __init__(self, ctx: NightContext, sr: int = 44100,
                 block_s: float = BLOCK_S,
                 reverb: ReverbConfig | None = None,
                 bed: SoundbedConfig | None = None) -> None:
        self.ctx = ctx
        self.sr = sr
        self.block_frames = int(block_s * sr)
        self._bed_overlap = min(int(_BED_OVERLAP_S * sr), self.block_frames)
        self.reverb = reverb if reverb is not None else ReverbConfig()
        self.bed = bed if bed is not None else SoundbedConfig()
        self._cache: OrderedDict[int, AudioBuffer] = OrderedDict()
        self._cache_bytes = 0

    # -- voices ---------------------------------------------------------
    def _rendered(self, voice: Voice) -> AudioBuffer:
        """This voice, generated, decayed and reverbed, with its tail."""
        cached = self._cache.get(voice.index)
        if cached is not None:
            self._cache.move_to_end(voice.index)
            return cached

        raw = render_voice(voice, self.sr, self.ctx.seed, self.ctx.sources)

        tail = int(_TAIL_S * self.sr)
        padded = AudioBuffer(
            np.pad(raw.data, ((0, tail), (0, 0))).astype(np.float32), self.sr)

        rng = iteration_rng(self.ctx.seed, voice.key, 1)
        decayed = apply_decay(padded, 1.0, voice.decay, rng)
        reverbed = apply_reverb(decayed, self.reverb)

        # apply_reverb's pedalboard backend prepends predelay_ms of silence to
        # the whole buffer, dry included, so frame 0 is no longer this voice's
        # birth. reverb_dry_offset measures exactly how much and we trim it
        # back off — keeping the tail, losing only the leading shift.
        offset = reverb_dry_offset(self.reverb, self.sr)
        trimmed = reverbed.data[offset:] if offset > 0 else reverbed.data
        if trimmed.shape[0] < voice.n_frames:
            trimmed = np.pad(
                trimmed, ((0, voice.n_frames - trimmed.shape[0]), (0, 0)))

        # The fade goes on last, over the *whole* padded buffer, because two
        # stages downstream of ``palette``'s own fade put audio back at the
        # ends of it. ``apply_decay`` mixes its noise floor in after
        # everything else, so without this a voice's birth stepped from exact
        # digital silence to broadband hiss in one sample; and the reverb tail
        # ends wherever the padding ends. Fading here means nothing in the
        # chain — present or future — can start or stop instantaneously.
        trimmed = trimmed * fade_envelope(trimmed.shape[0], self.sr)[:, None]
        wet = AudioBuffer(trimmed.astype(np.float32), self.sr)

        self._cache[voice.index] = wet
        self._cache_bytes += wet.data.nbytes
        self._cache.move_to_end(voice.index)
        while len(self._cache) > 1 and self._cache_bytes > _CACHE_BYTES:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.data.nbytes
        return wet

    # -- bed ------------------------------------------------------------
    def _bed_window(self, index: int) -> np.ndarray:
        """``block_frames + _BED_OVERLAP`` frames of bed, keyed by block.

        A window covers global frames ``[index * B, index * B + B + overlap)``
        — it deliberately runs past the end of its own block, so that the next
        block has something of *this* window's to fade out of. See ``_bed``.
        """
        overlap = self._bed_overlap
        arc = arc_at(index * self.block_frames / self.sr, self.ctx)
        weather = self.ctx.weather
        wetness = min(weather.precipitation_mm / 8.0, 1.0)
        level_db = (_BED_BASE_DB
                    + _BED_RAIN_BOOST_DB * wetness
                    + arc.level_db)

        rng = iteration_rng(self.ctx.seed, "night:bed", index)
        mono = colored_noise(self.block_frames + overlap, self.sr,
                             self.bed.noise_type, rng)
        # The bed must darken with the arc too, or late in the night — once
        # the voices are dim and sparse — the bed's untouched spectrum is most
        # of what is left, and the mix gets brighter in character exactly when
        # the arc wants it darkest.
        mono = _soft_lowpass(mono, self.sr, arc.brightness_hz)
        return (mono * db_to_amp(level_db)).astype(np.float32)

    def _bed(self, index: int) -> np.ndarray:
        """A block of noise bed, keyed by block so it stays independent.

        Only noise, never the binaural tone: a tone generated per block would
        restart its phase at every seam and click. Binaural belongs to a later
        plan that can carry absolute time into the generator.

        **Two overlapping windows, crossfaded, rather than one window per
        block.** Independent noise per block is fine while the noise is
        broadband — a seam step is indistinguishable from the sample-to-sample
        motion the signal already has. It stops being fine the moment the arc
        darkens the bed: lowpassing collapses the within-block motion and
        leaves the seam standing. Measured at 44.1 kHz mid-night, with one
        window per block, the step at a seam was 7.3x the largest step
        anywhere inside a block — the same metric, and past the same
        threshold, that ``test_consecutive_blocks_join_without_a_step``
        applies to the music.

        Window ``index`` runs ``_BED_OVERLAP_S`` past the end of block
        ``index``, and block ``index`` opens by fading from the tail of window
        ``index - 1`` into the head of window ``index``. Both windows are pure
        functions of their own index, so the block is still computable from
        ``index`` alone and block independence is untouched.

        (The circular convolution in ``_soft_lowpass`` was the suspected cause
        and is not it — but the number that used to be quoted here was wrong.
        It said "at most -41 dB relative to the block's peak", and that figure
        does not reproduce against this module's own input. Re-measured
        against a linearly-convolved reference, using the pink noise
        ``_bed_window`` actually generates at 44.1 kHz (seed 3, block 6, one
        whole window): the wrap reaches **-17.3 dB** relative to the block's
        peak at a 500 Hz cutoff and **-16.2 dB** at 3000 Hz, worst case
        -9.8 dB across twenty seed/block combinations. Two independently
        constructed linear references — zero-padded filtering, and an explicit
        zero-phase FIR convolved long — agree on those figures to the digit.

        What did survive the correction is the *shape* of the error, which is
        what the conclusion rested on. It is at the window's first and last
        samples, because that is where a circular filter reads the opposite
        end of its own window: above -60 dB only within 1.6 ms of each edge at
        500 Hz and 0.3 ms at 3000 Hz, with the interior matching the linear
        reference to -71.7 dB and -127.0 dB respectively. Those first and last
        samples are exactly the ones the equal-power ramp above multiplies by
        approximately zero, so the crossfade that fixed the seam attenuates
        this too. The one place it is not attenuated is the head of block 0,
        which has no previous window to cross out of. The seam was the noise,
        not the filter — but the filter's edge error is an order of magnitude
        larger than this docstring used to claim.)
        """
        if not self.bed.enabled or self.bed.noise_type in (None, "", "none"):
            return np.zeros((self.block_frames, 2), dtype=np.float32)

        overlap = self._bed_overlap
        current = self._bed_window(index)
        mono = current[:self.block_frames].copy()

        # Block 0 has nothing before it to fade out of, and ``iteration_rng``
        # would be handed a negative iteration if it were asked for one.
        if overlap > 0 and index > 0:
            previous = self._bed_window(index - 1)[self.block_frames:]
            # Equal-power, so two uncorrelated noises sum to a constant level
            # through the transition rather than dipping in the middle.
            ramp = np.linspace(0.0, np.pi / 2, overlap, dtype=np.float32)
            mono[:overlap] = (previous * np.cos(ramp)
                              + mono[:overlap] * np.sin(ramp))

        return mono.astype(np.float32)[:, None] \
            * np.ones((1, 2), dtype=np.float32)

    # -- blocks ---------------------------------------------------------
    def summed(self, index: int) -> np.ndarray:
        """Block ``index``, before the safety clip.

        Split out from ``block`` so that a headroom test has something it can
        actually fail against. Asserting ``max <= 1.0`` on ``block``'s output
        asserts nothing at all — the last thing ``block`` does is clip to that
        range — and two tests did exactly that while the real sum was reaching
        1.27 and clipping 9 blocks in 120. The clip is a guard against a case
        nobody predicted, not a level control, so what has to be measured is
        the number arriving at it.
        """
        start = index * self.block_frames
        end = start + self.block_frames
        out = np.zeros((self.block_frames, 2), dtype=np.float32)

        # A voice's reverb tail can reach a block its plan entry does not, so
        # the query window is widened by the tail rather than by guesswork.
        tail = int(_TAIL_S * self.sr)
        for voice in plan_voices(self.ctx, self.sr, max(start - tail, 0), end):
            # Degradation is per *voice*, not per block. Without this a single
            # voice raising anywhere in the chain took the whole ten seconds
            # with it and the player replaced music with pink noise; the spec
            # asks for "skip it, log it, continue — one bad voice is a few
            # seconds of slightly thinner texture."
            try:
                rendered = self._rendered(voice)
                take_from = max(start - voice.birth_frame, 0)
                take_to = min(end - voice.birth_frame, rendered.n_frames)
                if take_to <= take_from:
                    continue
                chunk = rendered.data[take_from:take_to]
                offset = max(voice.birth_frame - start, 0)
                out[offset:offset + len(chunk)] += chunk
            except Exception:
                _log.warning("night: skipping voice %d in block %d",
                             voice.index, index, exc_info=True)
                continue

        out += self._bed(index)
        return out

    def block(self, index: int) -> AudioBuffer:
        """Assemble block ``index``, needing nothing that came before it."""
        return AudioBuffer(np.clip(self.summed(index), -1.0, 1.0), self.sr)
