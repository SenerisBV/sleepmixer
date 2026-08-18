"""Two generators, a prepared loop, and the fade that keeps any of them from
being an event.

The synthesised textures are not trying to sound like a synthesiser. They are
trying to sound like something that was recorded and has since eroded,
because that is the family this program belongs to — and because everything
they produce is about to be handed to ``apply_decay``, which was written for
tape and behaves best on material with some noise and some drift already in
it. A ``"source"`` voice is the other half of that story: not synthesised at
all, but a prepared loop played back and tiled to fill the voice's life, so
that the ghost the planner paired it with has something real to fade from.

The hard rule is **no transients**. Every voice fades in and out over
``FADE_S`` seconds, and the fade is applied here rather than by the caller so
that no future caller can forget it.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np

from ..audio import AudioBuffer, load_audio
from ..util import iteration_rng
from .plan import Voice
from .sources import SourceProfile

# Long enough that arrival and departure are never noticed as moments. This is
# a taste value and a first draft.
FADE_S = 6.0

# Partials in a drone, as multiples of the fundamental, with the amplitude each
# gets. Weighted down steeply: the point is a fundamental with a halo, not an
# organ stop.
_PARTIALS = ((1.0, 1.00), (2.0, 0.32), (3.0, 0.14), (4.0, 0.07), (6.0, 0.04))

# How far each partial is allowed to drift in pitch and level, and how slowly.
_DETUNE_CENTS = 7.0
_DRIFT_DEPTH = 0.35
_DRIFT_MIN_HZ, _DRIFT_MAX_HZ = 0.013, 0.11

# How loud one voice is before the arc's level ceiling scales it.
#
# It has to leave room for every voice that can sound at once, and 0.35 did
# not: the pre-clip sum of a block reached 1.0576 at seed 11 and 1.2712 at
# seed 99, where 9 of the first 120 blocks clipped. Both clipping tests passed
# anyway, because they asserted ``max <= 1.0`` against functions whose last
# statement is ``np.clip(..., -1, 1)`` — an assertion that cannot fail.
#
# Lowering this rather than scaling by the number of concurrent voices is
# deliberate. A per-block concurrency scale would make one voice's level
# depend on its neighbours, so a cached voice could not be sliced at a
# constant gain and the level would step wherever the count changed — and it
# would put a second, unrelated level control in front of the arc's own
# ceiling, which is meant to be the thing that decides how loud a night is.
# A constant here is transparent to all of that: every voice moves together
# and ``arc.level_db`` still means what it says.
#
# 0.20 measured across seeds 3, 7, 11, 42, 99, 123 and 777 over the first 120
# blocks — the densest, loudest stretch of a night — puts the worst pre-clip
# peak at 0.76.
_PEAK = 0.20

# Prepared loops are small — seconds each — but a night asks for one several
# times a minute for eight hours. Bounded by bytes for the same reason
# `stream.py`'s voice cache is: a count is not a memory budget. Phase 1's
# voice cache was specified as 24 entries and turned out to hold 1.3 GB.
_LOOP_CACHE_BYTES = 128 * 1024 * 1024
_loop_cache: "OrderedDict[tuple[str, int], AudioBuffer]" = OrderedDict()
_loop_cache_bytes = 0


def _loop_for(path: str, sr: int) -> AudioBuffer | None:
    """A prepared loop at ``sr``, or ``None`` if it cannot be read.

    Module-level and shared across every ``NightStream`` in the process. That
    is safe for the same reason it is safe in ``stream.py``: the key is
    ``(path, sr)``, so two nights at different sample rates never collide on
    an entry, and two nights at the same sample rate reading the same path
    are reading the same bytes on disk and should see the same buffer. The
    cache is an optimisation and never an input: evicting it changes nothing
    about what comes out, which is what keeps block independence true — a
    render is a pure function of ``(path, sr)`` via the file on disk, not of
    whatever else happens to be resident in the cache at the time.
    """
    global _loop_cache_bytes
    key = (path, sr)
    hit = _loop_cache.get(key)
    if hit is not None:
        _loop_cache.move_to_end(key)
        return hit
    try:
        buf = load_audio(path, sr=sr).to_stereo()
    except Exception:
        return None
    if buf.n_frames <= 0:
        return None

    _loop_cache[key] = buf
    _loop_cache_bytes += buf.data.nbytes
    while len(_loop_cache) > 1 and _loop_cache_bytes > _LOOP_CACHE_BYTES:
        _, evicted = _loop_cache.popitem(last=False)
        _loop_cache_bytes -= evicted.data.nbytes
    return buf


def _source(voice: Voice, n: int, sr: int,
           profiles: tuple[SourceProfile, ...]) -> np.ndarray | None:
    """A prepared loop, tiled to ``n`` frames. ``None`` if unavailable.

    Every way this can fail — no matching profile, an index past the end, a
    file that has moved since `prepare` ran, a profile naming a zero-frame
    loop — costs this voice and nothing else. A person moves folders, and a
    night should survive it.
    """
    if n <= 0 or not profiles:
        return None
    profile = next((p for p in profiles if p.source_id == voice.source_id),
                   None)
    if profile is None:
        return None
    if not (0 <= voice.loop_index < len(profile.loop_paths)):
        return None
    loop = _loop_for(profile.loop_paths[voice.loop_index], sr)
    if loop is None or loop.n_frames <= 0:
        return None

    reps = int(np.ceil(n / loop.n_frames))
    tiled = np.tile(loop.data, (reps, 1))[:n]
    assert len(tiled) == n
    return tiled.astype(np.float32)


def fade_envelope(n: int, sr: int) -> np.ndarray:
    """A raised-cosine fade at both ends, halved if the voice is too short.

    Public because it is applied twice on the way to a block, in two different
    modules and for the same reason. This module fades the raw material so a
    generator cannot produce an attack; ``stream._rendered`` fades the *whole*
    padded, decayed, reverbed buffer so that nothing any later stage adds —
    the decay engine's noise floor in particular, which is mixed in after
    everything else — can start or stop instantaneously either. One envelope,
    so the two cannot drift apart.
    """
    fade = min(int(FADE_S * sr), n // 2)
    env = np.ones(n, dtype=np.float32)
    if fade > 0:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade,
                                              dtype=np.float32))
        env[:fade] = ramp
        env[-fade:] = ramp[::-1]
    return env


def _slow_drift(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """A gentle amplitude wobble, slow enough to read as breathing.

    The range is ``[1 - _DRIFT_DEPTH, 1.0]`` — currently [0.65, 1.0] — not
    0..1. It is a multiplier that never reaches zero on purpose: a drift that
    touched silence would be a gap, and a gap is an event.
    """
    rate = float(rng.uniform(_DRIFT_MIN_HZ, _DRIFT_MAX_HZ))
    phase = float(rng.uniform(0.0, 2 * np.pi))
    t = np.arange(n, dtype=np.float64) / sr
    return (1.0 - _DRIFT_DEPTH
            + _DRIFT_DEPTH * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t + phase))
            ).astype(np.float32)


def _drone(n: int, sr: int, pitch_hz: float,
           rng: np.random.Generator) -> np.ndarray:
    """Additive partials, each detuned and drifting on its own clock.

    ``t`` is float64 and the sine is evaluated before anything is narrowed to
    float32. A float32 time axis loses its last bits of resolution as the
    sample index climbs, and the phase error that follows is not white — it
    is a deterministic function of the argument, so it lands as a tonal
    sideband rather than as hiss. Over a four-minute voice at 44.1 kHz that
    was roughly 33 dB SNR with structure in it. float64 costs one temporary
    array and removes the whole question.
    """
    t = np.arange(n, dtype=np.float64) / sr
    out = np.zeros(n, dtype=np.float32)
    for multiple, amplitude in _PARTIALS:
        cents = float(rng.uniform(-_DETUNE_CENTS, _DETUNE_CENTS))
        freq = pitch_hz * multiple * (2.0 ** (cents / 1200.0))
        if freq >= sr / 2:
            continue
        phase = float(rng.uniform(0.0, 2 * np.pi))
        tone = np.sin(2 * np.pi * freq * t + phase).astype(np.float32)
        out += tone * amplitude * _slow_drift(n, sr, rng)
    return out


def _noise_band(n: int, sr: int, pitch_hz: float,
                rng: np.random.Generator) -> np.ndarray:
    """Pink-ish noise squeezed into a band around the pitch.

    Built in the frequency domain rather than with an IIR filter, because a
    resonant bandpass rung by noise is a very easy way to produce a whistle,
    and a whistle at 3 AM is the opposite of the brief.
    """
    spectrum = np.fft.rfft(rng.standard_normal(n).astype(np.float32))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    # A wide, gentle bell around the pitch — roughly an octave either side.
    with np.errstate(divide="ignore", invalid="ignore"):
        octaves = np.log2(np.maximum(freqs, 1e-6) / max(pitch_hz, 1e-6))
    shape = np.exp(-0.5 * (octaves / 0.8) ** 2)
    shape[freqs < 20.0] = 0.0

    band = np.fft.irfft(spectrum * shape, n=n).astype(np.float32)
    return band * _slow_drift(n, sr, rng)


def render_voice(voice: Voice, sr: int, seed: int,
                 profiles: tuple[SourceProfile, ...] = ()) -> AudioBuffer:
    """Generate one voice's raw material: stereo, faded, not yet decayed.

    The two synthesised textures generate their channels from the same draw
    with independent drift, so the voice has some width without being two
    unrelated sounds. A ``"source"`` voice instead plays back a prepared loop
    named by ``voice.source_id``/``voice.loop_index`` out of ``profiles``,
    tiled to fill its life; any way that can fail — no matching profile, a
    moved file, an out-of-range index — is silence, not a raised exception,
    same as every other read from disk on this path.

    ``voice.gain`` scales *every* texture, not only source voices: the
    source/ghost pair's balance is meaningless if only one side of it
    responds to the balance.
    """
    n = max(voice.n_frames, 1)
    rng = iteration_rng(seed, voice.key, 0)

    if voice.texture == "source":
        stereo = _source(voice, n, sr, profiles)
        if stereo is None:
            return AudioBuffer(np.zeros((n, 2), dtype=np.float32), sr)
    elif voice.texture in ("drone", "noiseband"):
        generate = _drone if voice.texture == "drone" else _noise_band
        left = generate(n, sr, voice.pitch_hz, rng)
        right = generate(n, sr, voice.pitch_hz, rng)
        stereo = np.stack([left, right], axis=1)
    else:
        raise ValueError(f"unknown texture: {voice.texture!r}")

    peak = float(np.abs(stereo).max())
    if peak > 0:
        stereo = stereo * (_PEAK * voice.gain / peak)
    stereo *= fade_envelope(n, sr)[:, None]

    return AudioBuffer(stereo.astype(np.float32), sr)
