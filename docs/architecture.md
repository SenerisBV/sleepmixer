# Architecture

This document covers the core render pipeline and the interactive layer built
on top of it (separation → loop → stretch → decay → reverb → sum → sound bed →
master, plus preview, sessions, and progress). It does not cover the server,
library store, or UI — those are Plans 2 and 3; see `docs/project-state.md`.

## The load-bearing property: decay is a pure function of progress

Everything interactive in this codebase rests on one fact about
`disintegration.apply_decay`: given a loop, a progress value in `[0, 1]`, a
decay config, and an RNG, it returns that stem exactly as it should sound at
that point in the arc — with no dependency on any other iteration. Repetition
400 of 1200 does not need repetitions 1 through 399 to have been computed
first. `disintegration.decayed_iteration` is the thin wrapper that turns an
`(iteration, n_iterations)` pair into a progress value and an
iteration-specific RNG, and `build_disintegrating_stream` is just a loop that
calls it once per repetition and crossfades the results together
(`sleepmix/disintegration.py`).

This is what makes a preview cheap. `preview.render_window` answers "what does
this sound like two-thirds of the way through" by computing a single
iteration — tens of milliseconds per stem (measured during development on a
6.4-second stereo loop at 44.1kHz: `apply_decay` at 23-24ms, `apply_reverb` at
9-34ms) — instead of rendering everything that precedes it. Without the
purity property, previewing
iteration 800 would mean either rendering iterations 1–800 (defeating the
point of a preview) or maintaining running state that could drift from a real
render.

The property does not hold for free — it had to be engineered in. The
obstacle is randomness: `apply_decay` draws noise for spectral holes,
dropouts, and the rising noise floor. A single shared `np.random.Generator`
threaded through all iterations of a stem (the natural way to do it) makes
iteration *i*'s draws depend on how many random numbers every prior iteration
consumed — which makes iteration *i* impossible to reproduce without replaying
everything before it. `util.iteration_rng` fixes this by deriving a fresh
generator from `(seed, stem, iteration)` alone, via `np.random.default_rng`
seeded with a tuple of `(seed, sha256(stem)[:8 bytes as int], iteration)`. Any
iteration of any stem can be reconstructed in isolation, forever. This is also
why `RenderSession` and `render_window` exist at all as separate objects
instead of just being a slice into `build_disintegrating_stream`'s loop: the
purity means there is no "stream" a preview needs access to, only a loop and
an iteration index.

The accepted cost of this change is that renders on this branch are not
byte-for-byte reproducible against renders from before it, because the
randomness now comes from a different source. See `docs/project-state.md`
for why that trade was made deliberately.

## What each module owns

- **`paths.py`** — where sleepmix keeps data on disk. `data_dir()` resolves to
  a stable per-user location (`~/Library/Application Support/sleepmix` on
  macOS, `%LOCALAPPDATA%\sleepmix` on Windows, `$XDG_DATA_HOME/sleepmix`
  elsewhere), overridable with the `SLEEPMIX_DATA_DIR` environment variable.
  `cache_dir()` is `data_dir() / "cache"`. Both create the directory if
  missing. This replaces a prior design where the separation cache lived at
  `.sleepmix_cache` relative to the current working directory — workable for
  a CLI invoked from one place, wrong for a long-lived server process that
  might be launched from anywhere.

- **`progress.py`** — the reporting and cancellation contract shared by every
  long-running operation. `ProgressEvent` is a structured
  `(stage, stem, fraction, message)` tuple, replacing a plain
  `Callable[[str], None]` that only ever gave a UI a sentence to print.
  `ProgressReporter.emit` clamps `fraction` to `[0, 1]` and refuses to let it
  go backwards — a progress bar that retreats reads as worse than one that
  stalls. `stage_range(lo, hi)` is a context manager that rescales `emit`'s
  local `0..1` argument into the `[lo, hi]` slice of the overall render, so
  each stage can report its own internal progress without knowing where it
  sits in the whole pipeline; `pipeline.run_pipeline` uses it to give each
  stem an even slice of the 0.15–0.85 range. `CancelToken` is a flag with a
  `check()` that raises `Cancelled`. It is polled at three points, listed in
  full under "Progress and cancellation contract" below; the one that carries
  the weight is inside `build_disintegrating_stream`'s per-iteration loop,
  because that is where a long render spends its time. Polling happens
  *between* iterations, since that is where abandoning the work is safe —
  mid-iteration cancellation is not supported. Note that `run_pipeline`'s
  per-stem loop does **not** itself call `cancel.check()`; it threads the
  token down into `_process_stem` instead.

- **`session.py`** — `RenderSession` holds one open song across a sequence of
  interactive edits. See the staging table below.

- **`preview.py`** — `render_window` renders one point in the decay arc for a
  subset (or all) of a session's stems, applying reverb, gain, and channel
  mapping in the same order `pipeline._process_stem` does, and using
  `config.plan_stem_configs` to pick which stems apply — the same function
  `pipeline._plan_jobs` calls — so preview and batch render cannot select
  different stems for the same config. `preview_iteration_index` maps a
  `progress` fraction to a concrete `(iteration, n_iterations)` pair using the
  same `disintegration.plan_iterations` the batch renderer uses, so the two
  paths agree on which repetition a given point in the arc corresponds to.
  `_reverbed_window` handles the one part of a window that cannot be computed
  from the window alone — see "Reverb on a window that has to loop" below.

- **`effects.py`** — reverb, via pedalboard when installed and a numpy
  Schroeder fallback otherwise. `reverb_dry_offset(cfg, sr)` reports how far
  `apply_reverb` displaces the dry signal, *measured* by pushing an impulse
  through the same call path with the wet level zeroed, and cached per
  `(sr, predelay_ms)`. It has to be measured rather than derived because the
  backends disagree: `_pedalboard_reverb` pre-delays the whole buffer before
  the plugin sees it, so dry and wet both come back shifted, while
  `_schroeder_reverb` pre-delays only the wet path. Anything that reverbs a
  fragment and wants the fragment back needs this number.

- **`audio.py`** — the `AudioBuffer` container, file I/O, resampling,
  normalization, and `sum_buffers`, the one implementation of "sum these stems
  at the widest channel count". `pipeline.run_pipeline` and
  `session.RenderSession` both derive the loop point from that sum; two
  implementations that merely happen to agree would let the preview audition a
  different part of the song than the render produces, which is the same
  failure class `config.plan_stem_configs` exists to prevent for stem
  selection.

- **`disintegration.py`** — the decay engine itself: lowpass sweep, spectral
  holes, dropouts, amplitude fade, and rising noise floor, each interpolated
  from a stem's `*_start` to `*_end` config across the arc. `plan_iterations`
  computes how many loop repetitions a target duration needs given the
  crossfade length; `build_disintegrating_stream` is the batch path that runs
  every iteration and crossfades them together into one buffer.

- **`config.py`** — `MixConfig` and its nested dataclasses, with per-field
  metadata (`label`, `unit`, `min`/`max`/`step`, `choices`, `help`) attached
  via `dataclasses.field(metadata=...)`. `config_schema()` walks those fields
  with `typing.get_type_hints` (needed because `from __future__ import
  annotations` turns `f.type` into a string) and returns a JSON-able
  description of every control a UI would need to build — bounds, labels, and
  help text derived from the same source of truth as validation, so a
  hard-coded frontend control set can't drift from what the config actually
  accepts. `plan_stem_configs(available, config)` is the one place that
  decides which `StemConfig`s apply given the stems that actually came back
  from separation: configured, enabled stems that exist, or — only if none of
  them match — one default `StemConfig` per available stem. That second case
  is what happens when Demucs isn't available and separation falls back to a
  single `mix` stem; both `pipeline._plan_jobs` and `preview.render_window`
  call this same function so they cannot disagree about stem selection.

- **`pipeline.py`** — `run_pipeline`, the full batch render: separate, find a
  shared loop on the summed reference signal, then per stem seamless-loop →
  time-stretch → disintegrate → reverb → gain → channel-map, sum, optional
  sound bed, resample, fade, peak-normalize, write. Loop detection runs once
  against the sum of all stems so every stem stays phase-aligned to the same
  beat grid.

- **`analysis.py`** — tempo/beat detection and loop-point selection via
  librosa, with a fixed-tempo fallback. An explicit `start_s`/`end_s` pair on
  `LoopConfig` (set by a UI when a user drags loop handles on a waveform)
  short-circuits detection entirely.

- **`cli.py`** — the `sleepmix render` / `sleepmix init-config` commands.
  `render` wires a `ProgressReporter` through `progress.echo_sink` so the
  terminal output is unchanged even though the pipeline now emits structured
  events instead of plain strings.

## Graceful degradation

Every optional heavy dependency — Demucs (`separation.py`), librosa
(`analysis.py`, `timestretch.py`), Rubber Band via `pyrubberband`
(`timestretch.py`), pedalboard (`effects.py`) — follows the same shape: the
import happens inside the function that needs it, never at module scope, and
every call site that reaches for one is wrapped in a `try/except Exception`
with a working fallback. This means the whole pipeline runs on `numpy`/`scipy`
alone, at reduced fidelity, with nothing to install beyond the core package —
`separation.py` falls back to a single `mix` stem, `analysis.py` to a
fixed-120-BPM guess, `timestretch.py` to plain resampling (which couples speed
and pitch — a lo-fi result the module's own docstring notes "happens to suit
the aesthetic anyway"), and `effects.py` to a hand-rolled Schroeder reverb.
`import sleepmix` must never fail because a multi-gigabyte ML dependency isn't
installed; the policy that guarantees this is: check for the dependency only
where it's used, and always have something that works without it.

One instance of this is deliberately not silent-and-safe: `separation.py`
catches every exception from the real Demucs call and warns via
`warnings.warn`, which is easy to miss outside a terminal. See
`docs/project-state.md` for why that's flagged as unfinished rather than
accepted.

## The `RenderSession` staging table

`RenderSession` exists because a preview needs the results of separation,
loop detection, and time-stretching to already be sitting in memory —
recomputing any of them per keystroke would cost seconds to tens of seconds,
which is the exact expense interactive preview is supposed to avoid. It
memoizes three stages, each invalidated only by the part of the config it
actually depends on:

| Stage | Method | Computed from | Invalidated by |
|---|---|---|---|
| Separation | `stems()` | `input_path`, `config.separation_model` | `separation_model` changing |
| Loop point | `loop_point()` | the summed reference signal, `config.loop` | `config.loop` changing, or a `separation_model` change (stems changed under it) |
| Prepared loop (sliced, seamless, stretched) | `prepared_loop(stem)` | `stems()[stem]`, `loop_point()`, `config.loop.crossfade_ms`, `config.tempo` | `config.loop` changing, `config.tempo` changing, or a `separation_model` change |

`update_config` compares the new config against cached keys (`_key` — a
sorted tuple of `dataclasses.asdict(section).items()`) for `loop` and `tempo`,
and discards downstream caches when they differ; a `separation_model` change
discards everything, since the stems themselves are gone. Decay parameters
and reverb are deliberately outside this table — they're not memoized at all,
because `preview.render_window` applies them fresh on every call as the thing
being auditioned.

### Mutating a held session's config

Only some config changes go through `update_config`, and the split is not
obvious from the outside, so it is stated on the `RenderSession` docstring as
well as here. `render_window` reads decay, gain, and reverb send *live* off
`session.config` — nothing downstream of them is cached — so mutating those in
place is both safe and the intended usage; the existing tests rely on it.
`loop`, `tempo`, and `separation_model` are the opposite: they determine the
memoized stages, and assigning one directly leaves the caches holding results
computed from the old value. There is no error. The preview simply keeps
showing the previous time-stretch, which is precisely the failure this class
exists to prevent. A server applying edits to long-lived sessions is where
this bites, so it should build a new `MixConfig` and call `update_config`
unless it knows the edit is confined to the safe set.

This staging is coarser than it could be: `config.loop`'s cache key is the
whole `LoopConfig`, so changing only `crossfade_ms` (which only affects
`make_seamless`, not `find_loop`) invalidates the loop point too, paying a
`find_loop` recompute (~1s) that a `crossfade_ms`-only change doesn't need to
pay. This is recorded as a known weakness in `docs/project-state.md` rather
than fixed here.

## Progress and cancellation contract

`run_pipeline` accepts an optional `reporter: ProgressReporter` and
`cancel: CancelToken`. If no reporter is given it builds one that adapts the
legacy `progress: Callable[[str], None]` parameter, so old callers keep
working. Stages emit at fixed overall-progress checkpoints (separate at 0.0,
loop at 0.10–0.15, stems spanning 0.15–0.85 split evenly via `stage_range`,
sound bed at 0.88, mastering at 0.92–1.0); a caller wanting a progress bar
reads `ProgressEvent.fraction` and does not need to know the stage
boundaries. Cancellation is checked at three points: immediately after
`separate()` returns (`pipeline.py:49-50`), once after the stem and sound-bed
sections finish and before mastering begins (`pipeline.py:77-78`), and inside
`build_disintegrating_stream`'s per-iteration loop, reached via `cancel`
threaded through `_process_stem` (`pipeline.py:69`, `pipeline.py:103`) into
that function. The per-iteration check is the one that matters most in
practice: because it sits inside the loop doing the actual expensive work, a
long render can be interrupted promptly *within* a stem, not merely between
stages, without leaving corrupted output — each iteration's contribution is a
complete, independent unit of work.

## Reverb on a window that has to loop

The UI plays a preview window on a loop while you tune, which constrains what
`render_window(..., reverb=True)` may return more than it first appears.
Reverbing one iteration on its own violates both constraints at once:
`effects._predelay` *prepends* the pre-delay, so the buffer comes back longer
than the loop it came from and opening with silence — a gap and a click on
every cycle.

Both symptoms come from the same cause, reverbing a fragment as though nothing
preceded it, so `preview._reverbed_window` gives it something that did. The
preceding iteration is rendered as leading context, reverbed together with the
window, and the window cut back out at `effects.reverb_dry_offset`. The window
is then exactly one loop long, its dry signal is sample-aligned with the
`reverb=False` window, and what fills the pre-delay region is the previous
iteration's reverb tail — the bleed a real render has and an isolated window
does not. Iteration 0 genuinely has nothing before it and so gets no context;
the trim still removes the leading silence.

One approximation remains and is not expected to close: the context is
concatenated where a real render crossfades consecutive iterations over
`cycle_crossfade_ms`, so the reverb hears a join the render does not. A wet
window is representative; a dry one is exact. See `docs/project-state.md`.

## Where data lives

`paths.data_dir()` — a per-user location outside the project directory — is
the only place sleepmix writes app data (currently just the separation cache
under `paths.cache_dir()`). `SLEEPMIX_DATA_DIR` overrides it entirely; the
test suite sets this to a fresh `tmp_path` for every test via the autouse
`isolated_data_dir` fixture in `tests/conftest.py`, so no test run touches a
real cache. Nothing else — no config, no library database, no rendered
output — is written outside paths the caller explicitly asks for
(`--output`, `save_audio`'s destination).
