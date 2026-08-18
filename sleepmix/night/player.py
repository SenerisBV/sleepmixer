"""Playback, and the two things that cannot be known in advance.

The renderer owns everything deterministic; this owns everything that is not.
That is one boundary, not two coincidences: live speech now, and the
microphone trim in Phase 2, are both things whose value at block *N* is not
knowable when block *N* is rendered. Putting them here is what lets
``stream.py`` keep the block-independence guarantee the whole design rests on.

**Nothing that goes wrong here may make a sound.** Every failure path ends in
less audio, never in different audio and never in a stop. A speech source that
raises loses its own voice and nothing else; a renderer that falls over is
replaced by a bed this module generates itself, which needs no plan and so is
available precisely when the thing that would have supplied one is the thing
that failed.
"""
from __future__ import annotations

import os
from typing import Callable

import numpy as np

from ..audio import AudioBuffer
from ..paths import data_dir
from ..soundbed import colored_noise
from ..util import db_to_amp, iteration_rng
from .clock import arc_at
from .speech import SpeechSource, over_the_air, through_a_wall
from .stream import NightStream

# How loud the player's own emergency bed is, before the arc scales it. Quiet
# enough to be a texture rather than an announcement that something is wrong.
_FALLBACK_BED_DB = -38.0

# How much of a radio feed's between-transmission static survives the gate.
_STATIC_GAIN = 0.22


def room_directory() -> str:
    """Where a comfort show goes. Created on demand.

    Phase 1 has no configuration, so the way media gets into a night is by
    being dropped into a folder rather than named on a command line.
    """
    path = os.path.join(str(data_dir()), "room")
    os.makedirs(path, exist_ok=True)
    return path


class NightPlayer:
    """Assemble the deterministic block, mix the live layer, hand it out."""

    def __init__(self, stream: NightStream, room: SpeechSource,
                 radio: SpeechSource, queue_depth: int = 3) -> None:
        self.stream = stream
        self.room = room
        self.radio = radio
        self.queue_depth = queue_depth

    # -- the live layer -------------------------------------------------
    def _speech(self, index: int, n_frames: int) -> np.ndarray:
        """Both speech sources, treated and summed. Never raises.

        The intelligibility ceiling is read here rather than at render time
        because this is where the speech is; the value comes from the same
        ``arc_at`` the renderer uses, so the two layers descend together.
        """
        arc = arc_at(index * self.stream.block_frames / self.stream.sr,
                     self.stream.ctx)
        out = np.zeros((n_frames, 2), dtype=np.float32)

        # Each source is paired with its own distance treatment: a room is
        # distant through a wall, a transmission is distant in space. The
        # try/except is per source, so one failing costs only its own voice.
        treated = (
            (self.room, lambda buf: through_a_wall(buf, arc.intelligibility)),
            (self.radio, lambda buf: over_the_air(buf, arc.intelligibility,
                                                  _STATIC_GAIN)),
        )
        for source, treat in treated:
            try:
                data = treat(source.read(n_frames)).to_stereo().data[:n_frames]
                out[:len(data)] += data
            except Exception:
                continue

        return out

    def mixed_block(self, index: int) -> AudioBuffer:
        """One block of music with the live layer summed on top."""
        music = self.stream.block(index)
        speech = self._speech(index, music.n_frames)
        mixed = np.clip(music.data + speech, -1.0, 1.0)
        return AudioBuffer(mixed.astype(np.float32), music.sr)

    # -- degradation ----------------------------------------------------
    def fallback_block(self, index: int) -> AudioBuffer:
        """A bed this module generates, for when the renderer cannot keep up.

        Deliberately does not go through ``NightStream``: the whole point is
        that this is available when the renderer is the thing that failed.
        """
        n = self.stream.block_frames
        sr = self.stream.sr
        arc = arc_at(index * n / sr, self.stream.ctx)
        rng = iteration_rng(self.stream.ctx.seed, "night:fallback", index)
        mono = colored_noise(n, sr, "pink", rng)
        level = db_to_amp(_FALLBACK_BED_DB + arc.level_db)
        data = (mono * level).astype(np.float32)[:, None] * np.ones((1, 2),
                                                                    np.float32)
        return AudioBuffer(np.clip(data, -1.0, 1.0), sr)

    # -- the loop -------------------------------------------------------
    def run(self, max_blocks: int | None = None,
            sink: Callable[[AudioBuffer], None] | None = None) -> None:
        """Produce blocks until ``max_blocks``, or forever.

        ``sink`` receives each block. The CLI passes one that writes to the
        sound device; the tests pass one that appends to a list, which is what
        makes every degradation path above assertable without hardware.
        """
        if sink is None:
            raise ValueError("run needs a sink to hand blocks to")

        index = 0
        try:
            while max_blocks is None or index < max_blocks:
                try:
                    block = self.mixed_block(index)
                except Exception:
                    block = self.fallback_block(index)
                sink(block)
                index += 1
        finally:
            for source in (self.room, self.radio):
                try:
                    source.close()
                except Exception:
                    pass
