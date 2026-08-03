"""A song held open for interactive work.

Rendering a preview means answering "what does this sound like at this point in
the decay arc" in about 100 ms. That is only possible if the expensive stages
before decay — separation, loop detection, time-stretching — are not redone on
every keystroke. This class stages those results and invalidates each one only
when the part of the config it actually depends on changes.

Ownership: one session per open song. It holds decoded audio in memory, so the
server should not keep an unbounded number of them alive.
"""
from __future__ import annotations

from dataclasses import asdict

from .analysis import LoopPoint, find_loop, slice_loop
from .audio import AudioBuffer
from .config import MixConfig
from .looping import make_seamless
from .paths import cache_dir
from .separation import separate
from .timestretch import slow_and_pitch


class RenderSession:
    def __init__(self, input_path: str, config: MixConfig,
                 separate_fn=None) -> None:
        self.input_path = input_path
        self.config = config
        # Injectable so tests can skip a ~10 s Demucs call per session.
        self._separate_fn = separate_fn or separate
        self._stems: dict[str, AudioBuffer] | None = None
        self._loop_point: LoopPoint | None = None
        self._prepared: dict[str, AudioBuffer] = {}
        self._loop_key = self._key(config.loop)
        self._tempo_key = self._key(config.tempo)

    # -- staged results -------------------------------------------------
    def stems(self) -> dict[str, AudioBuffer]:
        if self._stems is None:
            self._stems = self._separate_fn(
                self.input_path, self.config.separation_model,
                cache_dir=str(cache_dir()))
        return self._stems

    def stem_names(self) -> list[str]:
        return list(self.stems().keys())

    def loop_point(self) -> LoopPoint:
        if self._loop_point is None:
            self._loop_point = find_loop(self._reference(), self.config.loop)
        return self._loop_point

    def prepared_loop(self, stem: str) -> AudioBuffer:
        """The stem's loop, made seamless and time-stretched — ready to decay."""
        if stem not in self._prepared:
            buf = self.stems()[stem]
            loop = slice_loop(buf, self.loop_point())
            loop = make_seamless(loop, self.config.loop.crossfade_ms)
            self._prepared[stem] = slow_and_pitch(
                loop, self.config.tempo.speed, self.config.tempo.pitch_semitones)
        return self._prepared[stem]

    # -- invalidation ---------------------------------------------------
    def update_config(self, config: MixConfig) -> None:
        """Swap in a new config, discarding only the stages it invalidates."""
        loop_key = self._key(config.loop)
        tempo_key = self._key(config.tempo)
        if loop_key != self._loop_key:
            self._loop_point = None
            self._prepared.clear()
        elif tempo_key != self._tempo_key:
            self._prepared.clear()
        if config.separation_model != self.config.separation_model:
            self._stems = None
            self._loop_point = None
            self._prepared.clear()
        self.config = config
        self._loop_key = loop_key
        self._tempo_key = tempo_key

    # -- internals ------------------------------------------------------
    def _reference(self) -> AudioBuffer:
        """Sum of all stems — what loop detection runs against."""
        import numpy as np

        buffers = list(self.stems().values())
        n = max(b.n_frames for b in buffers)
        ch = max(b.n_channels for b in buffers)
        acc = np.zeros((n, ch), dtype=np.float32)
        for b in buffers:
            x = b.with_channels(ch).data
            acc[:x.shape[0]] += x
        return AudioBuffer(acc, buffers[0].sr)

    @staticmethod
    def _key(section) -> tuple:
        return tuple(sorted(asdict(section).items()))
