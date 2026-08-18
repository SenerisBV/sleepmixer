"""Human presence without a claim on you.

A police scanner and a sitcom you have seen forty times are opposite routes to
the same destination. The scanner is unfollowable *through obscurity* — clipped,
coded, half-buried in static. A comfort show is unfollowable *through
familiarity* — you already know how the scene ends, and the laugh track is a
room full of people being fine. Both remove narrative tension; neither asks for
attention. This module implements both doors.

The treatments differ and both are about distance. Radio is distant in space
(Task 8). A room is distant *through a wall*, which is not a workaround for the
fact that dialogue is intelligible but the actual thing being reproduced: a TV
on in the living room while you fall asleep on the couch.

Every source here is read by the *player*, never by ``stream.py``. That is the
boundary the block-independence invariant is drawn at.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

import numpy as np

from ..audio import AudioBuffer, load_audio
from ..config import ReverbConfig
from ..effects import apply_reverb, reverb_dry_offset
from ..looping import equal_power_crossfade
from ..util import db_to_amp

_log = logging.getLogger(__name__)

_MEDIA_SUFFIXES = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aif", ".aiff")

# The wall. A gentle slope from here down, moving lower as the night goes on.
_WALL_CLEAR_HZ = 900.0
_WALL_MURKY_HZ = 380.0

# How loud a room is allowed to be, relative to full scale, at each end of the
# intelligibility range.
_ROOM_CLEAR_DB = -26.0
_ROOM_MURKY_DB = -42.0

# A small room, not the cavern the stems sit in.
_WALL_REVERB = ReverbConfig(room_size=0.45, damping=0.75, wet=0.25, dry=0.85,
                            width=0.6, predelay_ms=12.0)

# The most any distance treatment may put on the output, whatever arrives at
# its input.
#
# It replaces a per-block peak normalisation that was, in effect, an automatic
# gain control: both treatments used to end with ``data * (target / peak)``,
# so a 60 dB change in source level produced no change at all in output, a
# pause between two lines of dialogue was lifted to the same peak as the
# dialogue, and — worst — the gain was recomputed from each ten-second block's
# own peak, so the room pumped on a 0.1 Hz cycle all night.
#
# A *fixed* ceiling is what makes it safe to apply a plain gain instead. It is
# the same number for every block, so it cannot introduce a step between two of
# them; and at any sane source level the gain alone lands far beneath it, so it
# never engages at all. It is a guard against a pathologically hot file, not a
# level control.
_TREATMENT_CEILING = 0.5

# How long a splice between two room files takes. Short enough not to be heard
# as a fade, long enough that the join is not a step — and a step at an
# arbitrary sample is a click.
_ROOM_XFADE_S = 0.08

# How close to the end of the current file the prefetch of the next one
# starts. Long enough that a slow decode still lands in time, short enough
# that two whole decoded files are not both resident for an entire episode.
_ROOM_PREFETCH_LEAD_S = 120.0

# How much live radio to hold ahead of playback. The network arrives when it
# arrives; this is the slack that lets ``read`` answer immediately anyway.
_RADIO_BUFFER_S = 20.0


class SpeechSource(Protocol):
    """Something that can always produce ``n_frames`` more of audio.

    ``read`` may never raise and may never block indefinitely: it is called
    from the playback path, where the only acceptable failure is silence.
    Implementations catch their own errors and return quiet rather than
    propagating.
    """

    def read(self, n_frames: int) -> AudioBuffer: ...

    def close(self) -> None: ...


class SilentSource:
    """The fallback every other source degrades into."""

    def __init__(self, sr: int, channels: int = 2) -> None:
        self.sr = sr
        self.channels = channels

    def read(self, n_frames: int) -> AudioBuffer:
        return AudioBuffer(
            np.zeros((n_frames, self.channels), dtype=np.float32), self.sr)

    def close(self) -> None:
        return None


class RoomSource:
    """Media the operator already owns, played end to end and then again.

    Files are decoded one at a time, and a file that fails to decode is
    skipped rather than raised — a corrupt download in the room directory
    should cost one file, not the night. If none of them can be read at all,
    every ``read`` returns silence and the player carries on with music.

    **Decoding happens off the playback path.** ``load_audio`` is a whole-file
    read plus a resample; on a forty-minute episode that is seconds of work,
    and it used to happen inside ``read``, which is inside the block the sound
    device is waiting for. The first file is decoded at construction — press
    time, not playback time — and every file after it is decoded by a daemon
    thread while the current one is still playing. ``read`` itself now only
    ever copies out of an array.

    If the prefetch is not ready when the current file runs out, the current
    file is played again from the top rather than waited for. That is the
    degradation this whole subsystem is built on — less variety, never a
    stall, never a gap — and it costs nothing, because the buffer needed is
    already in memory.

    **Splices are crossfaded.** Two files butt-joined at an arbitrary sample,
    or a file looped back to its own head, is a step, and a step is a click.
    The last ``_ROOM_XFADE_S`` of each buffer is held back rather than played,
    and blended into the head of whatever comes next.
    """

    def __init__(self, paths: list[str], sr: int) -> None:
        self.paths = list(paths)
        self.sr = sr
        self._xfade = max(int(_ROOM_XFADE_S * sr), 1)
        self._index = 0

        self._buffer: AudioBuffer | None = None
        # The pristine decode of whatever ``_buffer`` was made from. Looping
        # re-adopts *this* rather than ``_buffer``, so a file played round and
        # round does not accumulate one crossfade per lap in its own head.
        self._source: AudioBuffer | None = None
        self._usable = 0
        self._cursor = 0
        self._pending_tail: np.ndarray | None = None

        self._lock = threading.Lock()
        self._next: AudioBuffer | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # Only start decoding the *next* file once the current one is nearly
        # spent. A decoded file is tens to hundreds of megabytes, and holding
        # two of them for the whole of a forty-minute episode to save a
        # two-second decode is a bad trade.
        self._prefetch_lead = int(_ROOM_PREFETCH_LEAD_S * sr)

        if self.paths:
            self._adopt(self._decode_next())
            # With a single file there is nothing to prefetch: looping is
            # re-adopting the buffer already in hand, which needs no decode at
            # all and no second copy in memory.
            if self._buffer is not None and len(self.paths) > 1:
                self._thread = threading.Thread(
                    target=self._prefetch_loop, name="sleepmix-room",
                    daemon=True)
                self._thread.start()

    # -- decoding, off the playback path --------------------------------
    def _decode_next(self) -> AudioBuffer | None:
        """The next readable file, or None when none of them are.

        A file that decodes without error but yields zero frames — a
        truncated or empty download — is treated the same as one that failed
        to decode at all: skipped, not adopted. Accepting it as "loaded"
        would leave the cursor at ``n_frames == 0`` forever and nothing would
        ever advance again.
        """
        for _ in range(len(self.paths)):
            path = self.paths[self._index % len(self.paths)]
            self._index += 1
            try:
                loaded = load_audio(path, sr=self.sr).to_stereo()
            except Exception:
                _log.warning("night: skipping unreadable room file %s", path,
                             exc_info=True)
                continue
            if loaded.n_frames == 0:
                continue
            return loaded
        return None

    def _prefetch_loop(self) -> None:
        """Keep exactly one decoded file warm. Never raises out of itself."""
        while not self._stop.is_set():
            with self._lock:
                wanted = (self._next is None
                          and self._usable - self._cursor
                          <= self._prefetch_lead)
            if not wanted:
                self._stop.wait(0.1)
                continue
            try:
                decoded = self._decode_next()
            except Exception:  # pragma: no cover - _decode_next catches its own
                decoded = None
            if decoded is None:
                # Nothing in the directory decodes. Do not spin on it.
                self._stop.wait(1.0)
                continue
            with self._lock:
                self._next = decoded

    # -- splicing --------------------------------------------------------
    def _adopt(self, loaded: AudioBuffer | None) -> bool:
        """Make ``loaded`` the buffer being played, crossfading the seam."""
        if loaded is None or loaded.n_frames == 0:
            return False

        data = np.array(loaded.data, dtype=np.float32, copy=True)
        n = data.shape[0]

        if self._pending_tail is not None:
            m = min(len(self._pending_tail), n)
            if m > 0:
                data[:m] = equal_power_crossfade(self._pending_tail[:m],
                                                 data[:m])

        keep = min(self._xfade, n - 1) if n > 1 else 0
        if keep > 0:
            self._pending_tail = data[n - keep:].copy()
            self._usable = n - keep
        else:
            self._pending_tail = None
            self._usable = n

        self._buffer = AudioBuffer(data, self.sr)
        self._source = loaded
        self._cursor = 0
        return True

    def _advance(self) -> bool:
        """Move to the prefetched file, or replay the current one."""
        with self._lock:
            nxt, self._next = self._next, None
        if self._adopt(nxt):
            return True
        return self._adopt(self._source)

    # -- the playback path -----------------------------------------------
    def read(self, n_frames: int) -> AudioBuffer:
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if self._buffer is None:
            return AudioBuffer(out, self.sr)

        filled = 0
        while filled < n_frames:
            if self._cursor >= self._usable:
                if not self._advance():
                    break
            assert self._buffer is not None
            take = min(n_frames - filled, self._usable - self._cursor)
            if take <= 0:
                break
            out[filled:filled + take] = \
                self._buffer.data[self._cursor:self._cursor + take]
            self._cursor += take
            filled += take

        return AudioBuffer(out, self.sr)

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._buffer = None
        self._source = None
        self._next = None
        self._pending_tail = None


def room_sources_from(directory: str, sr: int) -> SpeechSource:
    """Whatever is in the room directory, or silence.

    Zero options is the whole point of Phase 1, so the way a comfort show gets
    into a night is by being dropped into a folder rather than named on a
    command line.
    """
    try:
        names = sorted(
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(_MEDIA_SUFFIXES)
        )
    except OSError:
        names = []
    return RoomSource(names, sr) if names else SilentSource(sr)


def _lowpass_fft(x: np.ndarray, cutoff_hz: float, sr: int) -> np.ndarray:
    """A gentle, phase-linear roll-off from ``cutoff_hz`` upward.

    Done in the frequency domain with a soft shoulder rather than with a steep
    IIR, because a wall is not a brick-wall filter and a resonant one would
    add a colour that reads as an effect.
    """
    n = len(x)
    spectrum = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    with np.errstate(divide="ignore", invalid="ignore"):
        octaves_above = np.log2(np.maximum(freqs, 1e-6) / max(cutoff_hz, 1e-6))
    shape = np.where(octaves_above <= 0, 1.0, 2.0 ** (-1.6 * octaves_above))
    return np.fft.irfft(spectrum * shape[:, None], n=n, axis=0).astype(np.float32)


def through_a_wall(buf: AudioBuffer, intelligibility: float) -> AudioBuffer:
    """Put a room on the other side of a wall.

    ``intelligibility`` runs 0..1 and comes from the night arc, so this gets
    murkier and quieter of its own accord as the night goes on. Both the cutoff
    and the level move with it: a distant room is not just a quiet one.
    """
    stereo = buf.to_stereo()
    if stereo.n_frames == 0:
        # An empty request is not an error, and the FFT below cannot take a
        # zero-length input.
        return stereo

    amount = float(min(max(intelligibility, 0.0), 1.0))
    cutoff = _WALL_MURKY_HZ + (_WALL_CLEAR_HZ - _WALL_MURKY_HZ) * amount
    level_db = _ROOM_MURKY_DB + (_ROOM_CLEAR_DB - _ROOM_MURKY_DB) * amount

    muffled = _lowpass_fft(stereo.data, cutoff, buf.sr)
    walled = apply_reverb(AudioBuffer(muffled, buf.sr), _WALL_REVERB)

    # Trim the pre-delay, exactly as ``stream._rendered`` does and for the
    # same reason: ``apply_reverb``'s pedalboard backend shifts the *whole*
    # buffer, dry included, by ``predelay_ms``. Truncating back to length
    # without trimming left 12 ms of exact digital silence at the head of
    # every treated block — and the player concatenates consecutive treated
    # blocks, so that became a per-block gap repeating at 0.1 Hz all night,
    # with a step into it at every seam. It also threw away 12 ms of source
    # per block. Both callers of ``apply_reverb`` in this package now trim.
    offset = reverb_dry_offset(_WALL_REVERB, buf.sr)
    data = walled.data[offset:offset + buf.n_frames]
    if len(data) < buf.n_frames:
        data = np.pad(data, ((0, buf.n_frames - len(data)), (0, 0)))

    # A plain gain, not a normalisation. See ``_TREATMENT_CEILING``: what
    # arrives quiet stays quiet, a pause stays a pause, and the level does
    # not step at a block boundary because nothing here is measured per block.
    data = data * db_to_amp(level_db)
    data = np.clip(data, -_TREATMENT_CEILING, _TREATMENT_CEILING)
    return AudioBuffer(data.astype(np.float32), buf.sr)


# -- radio ----------------------------------------------------------------
#
# The other door: unfollowable through obscurity rather than familiarity. HF
# and scanner audio is already intermittent, so the sparseness this design
# wants does not have to be invented — it is a property of the signal, and the
# gate below simply lets it through.

# Roughly telephone bandwidth: what a distant transmission survives as.
_AIR_LOW_HZ = 300.0
_AIR_HIGH_HZ = 3000.0

_AIR_CLEAR_DB = -24.0
_AIR_MURKY_DB = -40.0

_SQUELCH_SMOOTH_S = 0.05
_STREAM_CHUNK_S = 1.0


def squelch(x: np.ndarray, sr: int, floor_rms: float,
            open_ratio: float = 3.0) -> np.ndarray:
    """A 0..1 envelope that opens where the signal rises above the noise.

    Not a noise gate: the output is an envelope the caller *blends* with, so
    the static underneath can be kept at a lower level rather than removed.
    Removing it would throw away the part of a scanner feed that is doing the
    most work.

    Smoothed with a one-pole filter run forwards and then backwards, so the
    gate has no attack and no phase shift. A gate that snaps is a click, and a
    click at 3 AM is the thing this whole program is arranged around avoiding.

    **Each pass starts already settled on what it is being handed.** Run with
    the default zero initial conditions both passes started from a closed
    gate, so ``gate[:5]`` and ``gate[-5:]`` were exactly 0 no matter what was
    on the air — the radio layer was forced down to ``static_gain`` for the
    first and last ~50 ms of every ten-second block, which is a periodic duck
    at 0.1 Hz and a transmission straddling a seam chopped at both ends.
    ``lfilter_zi`` gives the steady-state conditions for a unit input, scaled
    here by the *mean of the first smoothing window* rather than by the single
    first sample. That distinction matters: ``raw`` is a rectified-signal
    indicator, so it toggles at twice the audio frequency and its first sample
    is 0 during any zero crossing — a continuous transmission would have
    opened the block at half gate on a coin flip.
    """
    from scipy.signal import lfilter, lfilter_zi

    mono = x.mean(axis=1) if x.ndim == 2 else x
    threshold = max(floor_rms, 1e-9) * open_ratio
    raw = (np.abs(mono) > threshold).astype(np.float64)
    if raw.size == 0:
        return raw.astype(np.float32)

    alpha = float(np.exp(-1.0 / max(_SQUELCH_SMOOTH_S * sr, 1.0)))
    b, a = np.array([1.0 - alpha]), np.array([1.0, -alpha])
    zi = lfilter_zi(b, a)
    warm = max(min(int(_SQUELCH_SMOOTH_S * sr), raw.size), 1)

    forward, _ = lfilter(b, a, raw, zi=zi * float(raw[:warm].mean()))
    flipped = forward[::-1]
    backward, _ = lfilter(b, a, flipped, zi=zi * float(flipped[:warm].mean()))
    return np.clip(backward[::-1], 0.0, 1.0).astype(np.float32)


_AIR_SHOULDER_OCTAVE = 5.0  # amplitude falloff exponent outside the band


def _bandpass_fft(x: np.ndarray, low_hz: float, high_hz: float,
                  sr: int) -> np.ndarray:
    """Soft-shouldered band limiting, in the frequency domain.

    The corner (``_AIR_HIGH_HZ`` = 3000) sits under an octave from where the
    band-limit test samples (4000 Hz), so a gentle shoulder is not steep
    enough to clear the band there: a -12 dB/octave amplitude slope (the
    original exponent of 2) still leaves double-digit percentages of energy
    above the corner once you sum across the wide tail up to Nyquist. 5.0
    (-30 dB/octave amplitude) clears it with comfortable margin while still
    being a shoulder, not a wall.
    """
    n = len(x)
    spectrum = np.fft.rfft(x, axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    with np.errstate(divide="ignore", invalid="ignore"):
        below = np.log2(np.maximum(freqs, 1e-6) / max(low_hz, 1e-6))
        above = np.log2(np.maximum(freqs, 1e-6) / max(high_hz, 1e-6))
    shape = (np.where(below >= 0, 1.0, 2.0 ** (_AIR_SHOULDER_OCTAVE * below))
             * np.where(above <= 0, 1.0,
                        2.0 ** (-_AIR_SHOULDER_OCTAVE * above)))
    return np.fft.irfft(spectrum * shape[:, None], n=n, axis=0).astype(np.float32)


def over_the_air(buf: AudioBuffer, intelligibility: float,
                 static_gain: float) -> AudioBuffer:
    """Put a transmission at the far end of an ionospheric path.

    The gate is applied as a *blend* rather than a mute: where it is open the
    transmission is at full weight, and where it is closed the same audio
    survives at ``static_gain``. Since what is there when the gate is closed is
    static, that is exactly the sparse-voices-over-hiss texture this is for.
    """
    amount = float(min(max(intelligibility, 0.0), 1.0))
    level_db = _AIR_MURKY_DB + (_AIR_CLEAR_DB - _AIR_MURKY_DB) * amount

    stereo = buf.to_stereo().data
    limited = _bandpass_fft(stereo, _AIR_LOW_HZ, _AIR_HIGH_HZ, buf.sr)

    floor = float(np.sqrt(np.mean(limited ** 2))) if limited.size else 0.0
    gate = squelch(limited, buf.sr, floor_rms=max(floor, 1e-6))
    blended = limited * (static_gain + (1.0 - static_gain) * gate[:, None])

    # A plain gain, not a normalisation — see ``_TREATMENT_CEILING``. A
    # normalisation here was worse than in the room's case, because the thing
    # it was normalising away is precisely the sparseness that makes radio
    # worth using: the quiet between transmissions was being lifted to the
    # same peak as the transmissions.
    blended = blended * db_to_amp(level_db)
    blended = np.clip(blended, -_TREATMENT_CEILING, _TREATMENT_CEILING)
    return AudioBuffer(blended.astype(np.float32), buf.sr)


def _open_stream(url: str, sr: int):
    """Open an HTTP audio stream and return something with ``read``/``close``.

    Imported inside the function per the graceful-degradation policy, and
    factored out so tests can replace the network without patching a library
    they do not otherwise care about.
    """
    import soundfile as sf
    import requests

    response = requests.get(url, stream=True, timeout=10)
    response.raise_for_status()

    handle = sf.SoundFile(response.raw, mode="r")

    class _Stream:
        def read(self, n_frames: int) -> np.ndarray:
            data = handle.read(n_frames, dtype="float32", always_2d=True)
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            return data[:, :2]

        def close(self) -> None:
            handle.close()
            response.close()

    return _Stream()


class RadioSource:
    """A live HTTP audio stream, or silence.

    Every failure mode — refused connection, DNS, a stream that stops
    mid-night, a decoder that gives up — lands in the same place: this source
    goes permanently quiet and the player carries on with music. Reconnection
    is deliberately not attempted here. A retry loop inside the playback path
    is a stall inside the playback path, and there is no version of "the
    network came back" that is worth a gap in the audio at 3 AM.

    **The network is never touched from ``read``.** Opening the stream is one
    HTTP request with a 10 s timeout, and filling ten seconds of audio means
    waiting for ten seconds of audio to arrive — both of which used to happen
    inside the playback path, where the deadline is the length of the device
    buffer. A daemon thread now does the connecting and the reading into a
    ring buffer of ``_RADIO_BUFFER_S``; ``read`` takes whatever has arrived
    and writes zeros for whatever has not. Underrun is silence in the speech
    layer alone, which is the degradation this design asks for everywhere.

    The ring is deliberately allowed to overwrite itself. This is live radio:
    if nothing has read for a while, the *old* audio is the wrong audio to
    keep.
    """

    def __init__(self, url: str, sr: int, chunk_s: float = _STREAM_CHUNK_S,
                 buffer_s: float = _RADIO_BUFFER_S) -> None:
        self.url = url
        self.sr = sr
        self.chunk_frames = max(int(chunk_s * sr), 1)

        self._capacity = max(int(buffer_s * sr), self.chunk_frames * 2)
        self._ring = np.zeros((self._capacity, 2), dtype=np.float32)
        self._write = 0
        self._available = 0

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._dead = False

    # -- the network, on its own thread ---------------------------------
    def _fill_loop(self) -> None:
        """Connect, then read forever into the ring. Never raises out."""
        stream = None
        try:
            stream = _open_stream(self.url, self.sr)
        except Exception:
            _log.warning("night: radio feed %s did not open", self.url,
                         exc_info=True)
            self._dead = True
            return

        try:
            while not self._stop.is_set():
                chunk = stream.read(self.chunk_frames)
                if chunk is None or len(chunk) == 0:
                    break
                self._write_ring(np.asarray(chunk, dtype=np.float32))
        except Exception:
            _log.warning("night: radio feed %s stopped", self.url,
                         exc_info=True)
        finally:
            self._dead = True
            try:
                stream.close()
            except Exception:
                pass

    def _write_ring(self, chunk: np.ndarray) -> None:
        if chunk.ndim == 1:
            chunk = np.stack([chunk, chunk], axis=1)
        chunk = chunk[:, :2]
        n = chunk.shape[0]
        if n == 0:
            return
        if n > self._capacity:
            chunk = chunk[-self._capacity:]
            n = self._capacity

        with self._lock:
            end = self._write + n
            if end <= self._capacity:
                self._ring[self._write:end] = chunk
            else:
                first = self._capacity - self._write
                self._ring[self._write:] = chunk[:first]
                self._ring[:end - self._capacity] = chunk[first:]
            self._write = end % self._capacity
            self._available = min(self._available + n, self._capacity)

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._fill_loop,
                                        name="sleepmix-radio", daemon=True)
        self._thread.start()

    # -- the playback path -----------------------------------------------
    def read(self, n_frames: int) -> AudioBuffer:
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if self._stop.is_set():
            return AudioBuffer(out, self.sr)
        self._ensure_started()

        with self._lock:
            take = min(n_frames, self._available)
            if take > 0:
                start = (self._write - self._available) % self._capacity
                end = start + take
                if end <= self._capacity:
                    out[:take] = self._ring[start:end]
                else:
                    first = self._capacity - start
                    out[:first] = self._ring[start:]
                    out[first:take] = self._ring[:end - self._capacity]
                self._available -= take

        return AudioBuffer(out, self.sr)

    def close(self) -> None:
        self._stop.set()
        self._dead = True
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)


def radio_source_from(url: str | None, sr: int) -> SpeechSource:
    """A radio source for ``url``, or silence when none is configured."""
    return RadioSource(url, sr) if url else SilentSource(sr)
