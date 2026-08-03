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
iteration — about 33ms per stem on the reference machine — instead of
rendering everything that precedes it. Without the purity property, previewing
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
  `check()` that raises `Cancelled`; call sites that do meaningful-length work
  in a loop (the per-stem loop in `run_pipeline`, and the per-iteration loop
  in `build_disintegrating_stream`) poll it between iterations because that is
  where abandoning the work is safe — mid-iteration cancellation is not
  supported, only between-iteration cancellation.

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
boundaries. Cancellation is checked at the top of the stem loop, once per
stem, and inside `build_disintegrating_stream`'s per-iteration loop — the
two points where a render can stop without leaving corrupted output, since
each iteration and each stem's contribution to `mix` is a complete,
independent unit of work.

## Where data lives

`paths.data_dir()` — a per-user location outside the project directory — is
the only place sleepmix writes app data (currently just the separation cache
under `paths.cache_dir()`). `SLEEPMIX_DATA_DIR` overrides it entirely; the
test suite sets this to a fresh `tmp_path` for every test via the autouse
`isolated_data_dir` fixture in `tests/conftest.py`, so no test run touches a
real cache. Nothing else — no config, no library database, no rendered
output — is written outside paths the caller explicitly asks for
(`--output`, `save_audio`'s destination).
