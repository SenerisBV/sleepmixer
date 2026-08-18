"""Block assembly: the deterministic half of the night, entire.

Nothing live reaches this module and nothing live may be added to it. That is
the boundary the design's central invariant is drawn at — a block of *music*
rendered in isolation is bit-identical to the same block rendered in sequence —
and it is only checkable because the speech layer is mixed at playback instead
of here.

**A voice is rendered once, whole, and then sliced.** Blocks are seconds and
voices are minutes, so every voice spans several blocks. Teaching the decay
engine to render part of a placement would mean changing the contract at the
heart of this codebase; rendering the voice complete and slicing it costs a few
tens of megabytes and changes nothing. It also solves the reverb problem for
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
from .palette import render_voice
from .plan import Voice, plan_voices

BLOCK_S = 10.0

# How many rendered voices to keep. A voice is at most four minutes, blocks are
# ten seconds, and a handful sound at once — so this holds every voice that can
# still be needed several times over. Eviction is least-recently-used, via
# ``move_to_end`` on every access.
_CACHE_SIZE = 24

# Reverb tail kept past a voice's death, so the room does not stop with it.
_TAIL_S = 6.0

# The bed's level is scaled by the arc alongside everything else, and pushed
# further by weather: a wet night sounds wet.
_BED_BASE_DB = -34.0
_BED_RAIN_BOOST_DB = 6.0


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
    """

    def __init__(self, ctx: NightContext, sr: int = 44100,
                 block_s: float = BLOCK_S,
                 reverb: ReverbConfig | None = None,
                 bed: SoundbedConfig | None = None) -> None:
        self.ctx = ctx
        self.sr = sr
        self.block_frames = int(block_s * sr)
        self.reverb = reverb if reverb is not None else ReverbConfig()
        self.bed = bed if bed is not None else SoundbedConfig()
        self._cache: OrderedDict[int, AudioBuffer] = OrderedDict()

    # -- voices ---------------------------------------------------------
    def _rendered(self, voice: Voice) -> AudioBuffer:
        """This voice, generated, decayed and reverbed, with its tail."""
        cached = self._cache.get(voice.index)
        if cached is not None:
            self._cache.move_to_end(voice.index)
            return cached

        raw = render_voice(voice, self.sr, self.ctx.seed)

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
        wet = AudioBuffer(trimmed.astype(np.float32), self.sr)

        self._cache[voice.index] = wet
        self._cache.move_to_end(voice.index)
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return wet

    # -- bed ------------------------------------------------------------
    def _bed(self, index: int) -> np.ndarray:
        """A block of noise bed, keyed by block so it stays independent.

        Only noise, never the binaural tone: a tone generated per block would
        restart its phase at every seam and click. Binaural belongs to a later
        plan that can carry absolute time into the generator.
        """
        if not self.bed.enabled or self.bed.noise_type in (None, "", "none"):
            return np.zeros((self.block_frames, 2), dtype=np.float32)

        arc = arc_at(index * self.block_frames / self.sr, self.ctx)
        weather = self.ctx.weather
        wetness = min(weather.precipitation_mm / 8.0, 1.0)
        level_db = (_BED_BASE_DB
                    + _BED_RAIN_BOOST_DB * wetness
                    + arc.level_db)

        rng = iteration_rng(self.ctx.seed, "night:bed", index)
        mono = colored_noise(self.block_frames, self.sr,
                             self.bed.noise_type, rng)
        # The bed must darken with the arc too, or late in the night — once
        # the voices are dim and sparse — the bed's untouched spectrum is most
        # of what is left, and the mix gets brighter in character exactly when
        # the arc wants it darkest.
        mono = _soft_lowpass(mono, self.sr, arc.brightness_hz)
        return (mono * db_to_amp(level_db)).astype(np.float32)[:, None] \
            * np.ones((1, 2), dtype=np.float32)

    # -- blocks ---------------------------------------------------------
    def block(self, index: int) -> AudioBuffer:
        """Assemble block ``index``, needing nothing that came before it."""
        start = index * self.block_frames
        end = start + self.block_frames
        out = np.zeros((self.block_frames, 2), dtype=np.float32)

        # A voice's reverb tail can reach a block its plan entry does not, so
        # the query window is widened by the tail rather than by guesswork.
        tail = int(_TAIL_S * self.sr)
        for voice in plan_voices(self.ctx, self.sr, max(start - tail, 0), end):
            rendered = self._rendered(voice)
            take_from = max(start - voice.birth_frame, 0)
            take_to = min(end - voice.birth_frame, rendered.n_frames)
            if take_to <= take_from:
                continue
            chunk = rendered.data[take_from:take_to]
            offset = max(voice.birth_frame - start, 0)
            out[offset:offset + len(chunk)] += chunk

        out += self._bed(index)
        return AudioBuffer(np.clip(out, -1.0, 1.0), self.sr)
