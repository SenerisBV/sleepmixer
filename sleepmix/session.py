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
from .audio import AudioBuffer, sum_buffers
from .config import MixConfig
from .looping import make_seamless
from .paths import cache_dir
from .separation import separate
from .timestretch import slow_and_pitch


class RenderSession:
    """One open song, with the expensive stages before decay held in memory.

    **Mutation contract — read this before editing a held session's config.**

    ``self.config`` is a plain attribute and callers do reach into it directly.
    Whether that is safe depends entirely on *which* field you touch, because
    only some of them feed the memoized stages:

    - **Safe to mutate in place on ``session.config``:** anything a preview
      recomputes from scratch on every call — ``stems`` (including each
      ``StemConfig``'s ``decay``, ``gain_db``, ``reverb_send`` and ``enabled``),
      ``reverb``, ``soundbed``, ``output``, and ``seed``. Nothing downstream is
      cached from these, so ``render_window`` picks the new value up
      immediately. The existing tests rely on exactly this.

    - **Must go through :meth:`update_config`:** ``loop``, ``tempo``, and
      ``separation_model``. These determine ``loop_point()``, the
      ``prepared_loop()`` cache, and ``stems()`` respectively. Assigning them
      directly leaves the caches populated with results computed from the *old*
      values, and there is no error — the preview simply keeps showing the
      previous time-stretch or the previous loop region, silently, which is the
      one failure this whole class exists to prevent.

    A server applying config edits to a long-lived session should therefore
    build the new ``MixConfig`` and hand it to :meth:`update_config` rather than
    patching fields onto the held one, unless it knows the edit is confined to
    the safe set.
    """

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
        """Sum of all stems — what loop detection runs against.

        Shares ``audio.sum_buffers`` with ``pipeline.run_pipeline`` so the loop
        point a session derives cannot drift from the one a render derives."""
        return sum_buffers(list(self.stems().values()))

    @staticmethod
    def _key(section) -> tuple:
        return tuple(sorted(asdict(section).items()))
