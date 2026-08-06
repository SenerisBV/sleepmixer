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

    - **Safe to mutate in place on ``session.config``:** each stem's ``decay``
      (curve, lowpass, amplitude, dropout, noise, spectral-hole settings),
      plus ``soundbed`` and ``seed``. Nothing downstream is cached from these,
      so ``render_window`` picks the new value up immediately. The existing
      tests rely on exactly this.

    - **Must go through :meth:`update_config`:** ``loop``, ``tempo``,
      ``separation_model``, ``reverb``, ``output``, and each stem's
      ``enabled``, ``gain_db`` and ``reverb_send``. The first three determine
      ``loop_point()``, the ``prepared_loop()`` cache, and ``stems()``
      respectively, as before. The latter four feed ``preview.master_gain``,
      which is now memoized on this class (see ``self.master_gain``) —
      mutating them directly leaves that cache holding a gain computed from
      the *old* values, and there is no error — the preview simply plays at
      the previous loudness, silently, which is exactly the defect this class
      exists to prevent.

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
        self._master_key_value = self._master_key(config)
        # Filled in by preview.master_gain, keyed by its ``reverb`` flag: a
        # gain calibrated wet mis-levels a dry window by several dB, so the two
        # signal paths need separate factors. It lives here rather than in
        # preview.py because it is invalidated by exactly the config changes
        # this class already tracks — and preview imports session, so session
        # cannot import preview to own the computation itself.
        self.master_gain: dict[bool, float] = {}

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
        master_key = self._master_key(config)
        if loop_key != self._loop_key:
            self._loop_point = None
            self._prepared.clear()
        elif tempo_key != self._tempo_key:
            self._prepared.clear()
        if config.separation_model != self.config.separation_model:
            self._stems = None
            self._loop_point = None
            self._prepared.clear()
        # master_gain is measured at progress 0, where apply_decay is a
        # passthrough, so decay settings alone can never move it — clearing on
        # every config swap (the registry does one per request) would double
        # the render cost of every preview for no reason. A different loop
        # means a different peak, so loop/tempo/model changes still clear it.
        if (master_key != self._master_key_value
                or loop_key != self._loop_key
                or tempo_key != self._tempo_key
                or config.separation_model != self.config.separation_model):
            self.master_gain.clear()
        self.config = config
        self._loop_key = loop_key
        self._tempo_key = tempo_key
        self._master_key_value = master_key

    # -- internals ------------------------------------------------------
    def _reference(self) -> AudioBuffer:
        """Sum of all stems — what loop detection runs against.

        Shares ``audio.sum_buffers`` with ``pipeline.run_pipeline`` so the loop
        point a session derives cannot drift from the one a render derives."""
        return sum_buffers(list(self.stems().values()))

    @staticmethod
    def _key(section) -> tuple:
        return tuple(sorted(asdict(section).items()))

    @staticmethod
    def _master_key(config: MixConfig) -> tuple:
        """What the master gain actually depends on.

        It is measured from iteration 0, where ``apply_decay`` returns the loop
        untouched — so no decay setting can move it. Dragging a decay slider
        must not invalidate this, or every preview pays a second window render.

        What is *deliberately* absent is as load-bearing as what is present.
        ``output.sample_rate`` is not here, and must not be added: the
        calibration window is ``preview.render_window``, which works end to end
        at ``loop.sr`` and never resamples — ``output.sample_rate`` is read in
        exactly one place in this codebase, ``pipeline.py``'s resample before
        normalizing, which every preview path has already finished before. It
        was added in Plan 3f Task 5 and reverted in the same plan's final
        review once someone measured the gain instead of tracing the
        invalidation chain: identical to the last digit at 22050, 44100 and
        48000, where ``peak_db`` and ``channels`` both move it. Adding it
        cannot change the value this key guards; it only makes the operator pay
        a whole extra calibration window on a rate change, which is the exact
        cost this docstring exists to avoid. The same measurement clears
        ``fade_in_s``/``fade_out_s`` and ``cycle_crossfade_ms`` — both are
        bit-identical too, but for two different reasons worth stating rather
        than waving at a branch. The fades: ``preview.py`` imports no fade
        function and no ``normalize_peak`` at all, so ``render_window`` cannot
        see them at any progress. The crossfade: ``cycle_crossfade_ms`` *is*
        read on the preview path — ``preview_iteration_index`` passes it to
        ``plan_iterations`` — but it only changes ``n_iterations``, and
        ``decayed_iteration`` computes
        ``progress = iteration / max(n_iterations - 1, 1)``
        (``disintegration.py:145``), which is 0 at iteration 0 whatever
        ``n_iterations`` turns out to be. See the level-matching entry in
        ``docs/project-state.md``.

        ``config.soundbed`` *is* here, and that is the opposite case from
        ``output.sample_rate`` above, not an exception to it. The test is the
        same one that field failed: does the calibration window actually read
        this value. As of this plan ``render_window`` imports
        ``build_soundbed`` and mixes a bed into the same iteration-0 window
        ``master_gain`` measures — whenever ``config.soundbed.enabled`` and no
        solo is in effect, which is exactly when the render carries a bed too.
        A window with the bed on has a different peak than one with it off, so
        this field moves the value this key guards, the same test
        ``output.sample_rate`` was measured against and failed. What decides
        membership in this tuple was never whether a field is *read* by
        ``render_window`` in the abstract — ``cycle_crossfade_ms`` is read and
        still excluded, ``output.sample_rate`` is not read at all — it is
        whether the calibration window's own output depends on it. Confirmed
        by reverting only this line while leaving the bed in
        ``render_window``: ``test_toggling_the_bed_clears_the_memoised_gain``
        fails, because a toggled bed no longer clears the stale factor. See
        ``docs/project-state.md`` for the ``output.sample_rate`` measurement
        this reasoning mirrors."""
        return (
            tuple(sorted(asdict(config.reverb).items())),
            config.output.peak_db,
            config.output.channels,
            tuple((sc.name, sc.enabled, sc.gain_db, sc.reverb_send)
                  for sc in config.stems),
            tuple(sorted(asdict(config.soundbed).items())),
        )
