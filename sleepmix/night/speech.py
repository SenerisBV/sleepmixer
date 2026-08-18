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

import os
from typing import Protocol

import numpy as np

from ..audio import AudioBuffer, load_audio
from ..config import ReverbConfig
from ..effects import apply_reverb
from ..util import db_to_amp

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

    Files are decoded lazily, one at a time, and a file that fails to decode is
    skipped rather than raised — a corrupt download in the room directory
    should cost one file, not the night. If none of them can be read at all,
    every ``read`` returns silence and the player carries on with music.
    """

    def __init__(self, paths: list[str], sr: int) -> None:
        self.paths = list(paths)
        self.sr = sr
        self._index = 0
        self._buffer: AudioBuffer | None = None
        self._cursor = 0
        self._exhausted = False

    def _advance(self) -> bool:
        """Load the next readable file. False when none of them are.

        A file that decodes without error but yields zero frames — a
        truncated or empty download — is treated the same as one that failed
        to decode at all: skipped, not adopted. Accepting it as "loaded"
        would leave the cursor at ``n_frames == 0`` forever, and ``read``
        would call back in on every iteration without ever making progress —
        an infinite loop, which is exactly what the never-blocks guarantee
        forbids.
        """
        for _ in range(len(self.paths)):
            path = self.paths[self._index % len(self.paths)]
            self._index += 1
            try:
                loaded = load_audio(path, sr=self.sr).to_stereo()
            except Exception:
                continue
            if loaded.n_frames == 0:
                continue
            self._buffer = loaded
            self._cursor = 0
            return True
        return False

    def read(self, n_frames: int) -> AudioBuffer:
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if self._exhausted or not self.paths:
            return AudioBuffer(out, self.sr)

        filled = 0
        while filled < n_frames:
            if self._buffer is None or self._cursor >= self._buffer.n_frames:
                if not self._advance():
                    self._exhausted = True
                    break
            assert self._buffer is not None
            take = min(n_frames - filled,
                       self._buffer.n_frames - self._cursor)
            out[filled:filled + take] = \
                self._buffer.data[self._cursor:self._cursor + take]
            self._cursor += take
            filled += take

        return AudioBuffer(out, self.sr)

    def close(self) -> None:
        self._buffer = None


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

    data = walled.data[:buf.n_frames]
    if len(data) < buf.n_frames:
        data = np.pad(data, ((0, buf.n_frames - len(data)), (0, 0)))

    peak = float(np.abs(data).max())
    if peak > 0:
        data = data * (db_to_amp(level_db) / peak)
    return AudioBuffer(data.astype(np.float32), buf.sr)
