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

import logging
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

from ..audio import AudioBuffer
from ..paths import data_dir
from ..soundbed import colored_noise
from ..util import db_to_amp, iteration_rng
from .clock import arc_at
from .speech import SpeechSource, over_the_air, through_a_wall
from .stream import NightStream

_log = logging.getLogger(__name__)

# How loud the player's own emergency bed is, before the arc scales it. Quiet
# enough to be a texture rather than an announcement that something is wrong.
_FALLBACK_BED_DB = -38.0

# How long the consumer waits for a rendered block before giving up on it and
# playing its own bed instead. Short, because the thing it is racing is a
# sound device with a buffer measured in tens of milliseconds — a wait long
# enough to be worth having is already an underrun.
_QUEUE_WAIT_S = 0.25

# How long ``run`` lets the renderer fill the queue before the first block is
# played. Nothing is on the air yet at that point, so this is start-up latency
# rather than a gap — the one moment in a night when waiting for the renderer
# costs nothing. Without it a night opens on the emergency bed every time,
# because the first block cannot possibly be ready within ``_QUEUE_WAIT_S``.
_PRIME_WAIT_S = 5.0

# How much of a radio feed's between-transmission static survives the gate.
_STATIC_GAIN = 0.22

# How long the output takes to cross between music and the player's own bed,
# in either direction. Short enough not to read as a fade, long enough not to
# be a step: the two signals differ by more than a factor of ten in level, so
# butting them together put a jump at the seam 7.58x the largest motion
# anywhere inside a block — past the same 4x threshold the music's and the
# bed's own seam tests apply.
_SEAM_S = 0.075

# A transient sink failure (one dropped audio-device write) is absorbed and
# the night carries on. This many *consecutive* failures means the device is
# gone, not hiccuping, and there is nothing left to degrade to — so ``run``
# ends the night rather than spinning on a dead output forever.
_MAX_CONSECUTIVE_SINK_FAILURES = 3


def room_directory() -> str:
    """Where a comfort show goes. Created on demand.

    Phase 1 has no configuration, so the way media gets into a night is by
    being dropped into a folder rather than named on a command line.
    """
    path = os.path.join(str(data_dir()), "room")
    os.makedirs(path, exist_ok=True)
    return path


class NightPlayer:
    """Render ahead, mix the live layer at the output, hand it out.

    Two threads, and the split between them is the same split the whole
    design rests on. The producer renders music blocks — deterministic,
    computable in advance, therefore worth computing in advance — into a
    ``queue_depth``-deep queue. The consumer takes them, sums the live speech
    layer on at the moment the block is handed to the device, and plays them.
    Nothing live crosses into the producer, which is what keeps ``stream.py``
    testable for block independence.
    """

    def __init__(self, stream: NightStream, room: SpeechSource,
                 radio: SpeechSource, queue_depth: int = 3) -> None:
        self.stream = stream
        self.room = room
        self.radio = radio
        self.queue_depth = max(int(queue_depth), 1)
        # The render thread, while ``run`` is running. Held on the instance so
        # a test can assert it does not outlive the call.
        self._producer: threading.Thread | None = None

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

    def _mix(self, index: int, music: AudioBuffer) -> AudioBuffer:
        """Sum the live layer onto an already-rendered block of music.

        Kept separate from ``mixed_block`` because ``run`` renders on one
        thread and mixes on another: the speech has to be read at the moment
        the block is handed to the device, not at the moment it was rendered,
        or it would be as stale as the queue is deep.
        """
        speech = self._speech(index, music.n_frames)
        mixed = np.clip(music.data + speech, -1.0, 1.0)
        return AudioBuffer(mixed.astype(np.float32), music.sr)

    def summed_mix(self, index: int) -> np.ndarray:
        """Music plus speech, before either safety clip.

        The counterpart of ``NightStream.summed`` and there for the same
        reason: a headroom assertion made against ``mixed_block`` cannot fail,
        because ``mixed_block`` clips.
        """
        music = self.stream.summed(index)
        return music + self._speech(index, music.shape[0])

    def mixed_block(self, index: int) -> AudioBuffer:
        """One block of music with the live layer summed on top."""
        return self._mix(index, self.stream.block(index))

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

    def _seam_frames(self) -> int:
        return max(min(int(_SEAM_S * self.stream.sr),
                       self.stream.block_frames), 1)

    def _cross_into(self, block: AudioBuffer,
                    tail: np.ndarray) -> AudioBuffer:
        """Open ``block`` by crossing over from the block before it.

        Used only where the *kind* of block changes — music into the player's
        own bed, or back — because that is the only boundary where the two
        sides were generated by different things at different levels. Music
        joins music at the renderer, and the bed joins the bed by being noise;
        neither needs help.

        **The outgoing material is the previous block's tail, reversed.** The
        crossfade has to start from the exact sample the device last played,
        and by the time this is called that block is already gone — nothing
        can be faded out of it after the fact, and there is no continuation of
        it to fade with either: if the renderer had one, this would not be a
        fallback. Reversing the tail gives a signal that begins on that last
        sample and carries on with the same spectrum and the same texture, so
        ``out[0]`` is exactly what the device just played and the step at the
        seam is zero by construction rather than by measurement. Time-reversed
        noise is noise, and time-reversed drone is drone; it is one of the few
        places where having no future is not a problem.

        Equal-power (cosine/sine), for the reason ``stream._bed`` is: the two
        sides are uncorrelated, so a linear crossfade would dip in the middle
        and a dip is as audible as a step.
        """
        n = min(len(tail), block.n_frames)
        if n < 2:
            return block
        outgoing = np.asarray(tail[::-1], dtype=np.float32)
        ramp = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)[:, None]
        data = block.data.copy()
        data[:n] = outgoing * np.cos(ramp) + data[:n] * np.sin(ramp)
        return AudioBuffer(
            np.clip(data, -1.0, 1.0).astype(np.float32), block.sr)

    # -- the loop -------------------------------------------------------
    def _render_ahead(self, blocks: "queue.Queue", stop: threading.Event,
                      max_blocks: int | None) -> None:
        """The producer: render block after block into ``blocks``.

        Runs on its own thread so that rendering and playing overlap. They
        have to: a block containing a voice birth costs 0.68–1.09 s to render
        at 44.1 kHz, a device buffer is 0.05–0.2 s, and early in the night a
        voice is born every 20–70 s — so a loop that rendered block *i*, wrote
        it, then rendered *i+1* underran once or twice a minute. What plays
        during a long render is the block before it, already queued.

        A block that fails to render is queued as ``None`` rather than
        dropped, so the consumer knows to put its own bed in that slot instead
        of silently shortening the night.
        """
        index = 0
        while not stop.is_set() and (max_blocks is None or index < max_blocks):
            try:
                music = self.stream.block(index)
            except Exception:
                _log.warning("night: block %d failed to render", index,
                             exc_info=True)
                music = None

            while not stop.is_set():
                try:
                    blocks.put((index, music), timeout=0.1)
                    break
                except queue.Full:
                    continue
            index += 1

    def run(self, max_blocks: int | None = None,
            sink: Callable[[AudioBuffer], None] | None = None) -> None:
        """Play blocks until ``max_blocks``, or forever.

        ``sink`` receives each block. The CLI passes one that writes to the
        sound device; the tests pass one that appends to a list, which is what
        makes every degradation path above assertable without hardware.

        **Rendering runs ahead of playback**, on the producer thread above,
        into a ``queue_depth``-deep queue. This loop is the consumer: it takes
        a block, mixes the live speech layer onto it *here* — the spec is
        explicit that the live layer is summed at the output, and mixing it in
        the producer would make it up to ``queue_depth`` blocks stale — and
        hands it to the sink.

        When the queue is empty the consumer does not wait for the renderer.
        It plays ``fallback_block`` instead: pink noise at the arc's current
        level, which needs no plan and so is available precisely when the
        thing that would have supplied one is the thing that fell behind. That
        is the design's own answer to "render worker falls behind", and it is
        what the fallback bed exists for.

        Two things make that bed bearable for more than one block at a time,
        and both were missing while the path was reachable only by exception.
        A fallback is keyed by how many blocks have been *played* rather than
        by how far the renderer got, so a run of fallbacks is a run of
        *different* noise rather than the same ten seconds looped; and the
        boundary between music and bed is
        crossed over ``_SEAM_S`` in either direction rather than stepped
        (``_cross_into``), because that is the one place in this design where
        two signals that know nothing about each other are butted together.

        A ``sink`` failure is treated the same as a renderer failure: a
        single one is absorbed and the loop moves on to the next block. Only
        ``_MAX_CONSECUTIVE_SINK_FAILURES`` in a row ends the night, and even
        then this returns quietly rather than raising — a dead device is not
        a reason for a traceback at 3 AM.
        """
        if sink is None:
            raise ValueError("run needs a sink to hand blocks to")

        stop = threading.Event()
        blocks: queue.Queue = queue.Queue(maxsize=self.queue_depth)
        producer = threading.Thread(
            target=self._render_ahead, args=(blocks, stop, max_blocks),
            name="sleepmix-night-render", daemon=True)
        self._producer = producer
        producer.start()

        deadline = time.monotonic() + _PRIME_WAIT_S
        while (blocks.empty() and producer.is_alive()
               and time.monotonic() < deadline):
            stop.wait(0.01)

        delivered = 0
        consecutive_sink_failures = 0
        seam = self._seam_frames()
        previous_tail: np.ndarray | None = None
        previous_was_bed: bool | None = None
        try:
            while max_blocks is None or delivered < max_blocks:
                try:
                    index, music = blocks.get(timeout=_QUEUE_WAIT_S)
                except queue.Empty:
                    index, music = None, None

                # ``delivered`` — how many blocks have gone to the device —
                # is what keys a fallback, and it is deliberately not the
                # renderer's index. It advances once per block played, on
                # every path, so no two fallbacks in a run can ever be handed
                # the same number.
                #
                # That matters because ``fallback_block`` is a pure function
                # of ``(seed, "night:fallback", index)``. A counter that
                # advanced only when a real block arrived — which is what this
                # loop used to have — made a thirty-second stall one
                # ten-second loop played three times, and repetition and
                # pattern are what this design argues wake people. It is also
                # the truer arc position of the two when the renderer is
                # behind: what the arc wants to know is how long the night has
                # been playing, not how far the renderer got.
                if music is None:
                    block = self.fallback_block(delivered)
                    is_bed = True
                else:
                    is_bed = False
                    try:
                        block = self._mix(index, music)
                    except Exception:
                        _log.warning("night: mixing block %d failed", index,
                                     exc_info=True)
                        block = self.fallback_block(delivered)
                        is_bed = True

                # Music and the bed differ by more than a factor of ten in
                # level, so the boundary between them is the one seam in this
                # design that a listener could hear. It is crossed rather than
                # stepped, in both directions. Nothing here reaches the
                # renderer: block independence is a property of
                # ``NightStream``, and this happens downstream of it, on the
                # buffer that is about to be handed to the device.
                if (previous_tail is not None and previous_was_bed is not None
                        and is_bed != previous_was_bed):
                    block = self._cross_into(block, previous_tail)
                previous_was_bed = is_bed
                previous_tail = block.data[-seam:].copy()

                try:
                    sink(block)
                except Exception:
                    consecutive_sink_failures += 1
                    if consecutive_sink_failures >= _MAX_CONSECUTIVE_SINK_FAILURES:
                        return
                else:
                    consecutive_sink_failures = 0

                delivered += 1
        finally:
            stop.set()
            # Drain one slot so a producer parked on a full queue can notice
            # the stop and leave, rather than being joined while blocked.
            try:
                blocks.get_nowait()
            except queue.Empty:
                pass
            producer.join(timeout=5.0)
            self._producer = None
            for source in (self.room, self.radio):
                try:
                    source.close()
                except Exception:
                    pass
