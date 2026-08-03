# Project state

Status as of the end of the `feat/core-hooks` branch (Plan 1 of the spec, all
10 tasks complete). This is the branch that gave the pipeline the hooks a
local web UI needs — session staging, cheap preview, structured progress,
stable data paths, a config schema — without building the UI itself. Read
`docs/architecture.md` first for how the pieces fit together; this document
is about what's true right now, what was traded off to get here, and what's
explicitly not done yet.

## What's built

Everything under "What each module owns" in `docs/architecture.md`:
`paths.py`, `progress.py`, `session.py`, `preview.py`, the config schema in
`config.py`, and the pre-existing render pipeline (`pipeline.py`,
`analysis.py`, `separation.py`, `timestretch.py`, `disintegration.py`,
`effects.py`, `soundbed.py`, `looping.py`) unchanged in behavior except where
noted below. The CLI (`cli.py`) still only does `render` and `init-config`.

## What's not built here

Nothing in this branch serves HTTP. The FastAPI server, the SSE progress
endpoint, the background job manager, and the SQLite library store (songs,
presets, renders) are Plan 2. The React SPA — library view, song view, mixer,
render screen, schema-driven controls consuming `config_schema()`, Web Audio
buffer swapping at loop boundaries using `render_window` — is Plan 3. Segment
selection and arrangement, output length as an arrangement property, and a
bundled desktop app are noted in the spec as future work beyond either plan.
This branch built the load-bearing capabilities those plans need; it does not
expose any of them to a user who isn't calling Python directly.

## Accepted changes and caveats

**Renders are no longer byte-for-byte reproducible against output generated
before this branch.** `util.iteration_rng` derives each iteration's RNG from
`(seed, stem, iteration)` instead of drawing from one `np.random.Generator`
threaded through the whole stream. The old approach made iteration *i*'s
noise depend on every draw before it, which made it impossible to reproduce a
single iteration without replaying the entire stem from the start — exactly
the cost interactive preview exists to avoid. This was a deliberate trade: a
preview that cannot match what the real render eventually produces at that
point is worse than no preview at all, and RNG determinism-by-history isn't a
property anyone was relying on (the render is still deterministic for a
given seed, just via a different derivation). If you have renders from before
this branch that you need to reproduce exactly, they cannot be — regenerate
them on this code if that matters.

**A preview window is bit-identical to the corresponding render iteration
pre-reverb, but only representative of it with reverb on.** `render_window`
applies each stem's decay and reverb (with that stem's `reverb_send`) in the
same order `pipeline._process_stem` does, so a dry preview and the dry render
at the same iteration produce identical samples. With reverb enabled they
diverge slightly, because a preview window is rendered in isolation and has
no reverb tail bleeding in from the *previous* iteration — a real render's
reverb is a continuous process across the whole stream, a preview's is not.
This was found and partially fixed during Task 9's review (see the addendum
in `.superpowers/sdd/2026-08-03-core-hooks/task-10-brief.md`); the remaining
tail-bleed gap is inherent to rendering a window in isolation and is not
expected to close without either rendering more context around the window or
approximating the tail, neither of which has been done.

**The separation cache moved.** It used to live at `.sleepmix_cache/`
relative to the working directory; it now lives under
`paths.cache_dir()` (a per-user app-data directory, see
`docs/architecture.md`). This repository still has a `.sleepmix_cache/` at
its root — roughly 170MB, one cached song — left over from before this
branch. It is orphaned: nothing on this branch reads it, so that song will
be re-separated (a real Demucs call, ~10s+ depending on hardware) the next
time it's rendered. It can be deleted; nothing here depends on it existing.

## Scheduled for Plan 2, not fixed here

**The silent Demucs fallback is still silent.** `separation.py` catches every
exception from the real separation call and falls back to a single `mix`
stem, surfacing the failure only via `warnings.warn`. That's adequate for a
CLI running in a terminal a person is watching. It is not adequate for a UI:
a user would configure per-stem decay, get back one undifferentiated stem,
and have no indication why their vocal-only decay setting did nothing. Making
this an explicit, visible piece of song state is Plan 2's job, not this
branch's — this branch doesn't have anywhere to surface it to.

**librosa's first call is cold.** librosa's beat-tracking and effects
functions are numba-JIT-compiled on first use in a process. During
development of this branch, one first call exceeded a two-minute test
timeout; the second call in the same process took 0.9s. Nothing in this
branch warms that up. A startup warm-up pass — calling the relevant librosa
functions once on dummy audio before a server starts accepting requests — is
scheduled for Plan 2, since only a long-lived server process benefits from
paying that cost once instead of on a user's first real request.

## Known weaknesses, deferred deliberately

These were identified and left as-is; each has a reason it wasn't worth
fixing in this branch.

- **`RenderSession`'s loop-stage cache key is coarser than it needs to be.**
  It covers all of `LoopConfig`, so changing only `crossfade_ms` — which only
  feeds `make_seamless`, not `find_loop` — invalidates the loop point and
  pays a ~1s `find_loop` recompute anyway. The fix is to split the cache key
  so `crossfade_ms` invalidates only `prepared_loop`'s cache, not
  `loop_point()`'s. Not done because no caller yet changes `crossfade_ms`
  interactively without also touching something that already invalidates
  the loop.

- **`util.iteration_rng` does not validate `seed >= 0`.** `numpy`'s
  `SeedSequence` requires non-negative entropy; a negative seed will raise
  deep inside `numpy`, not at the point where the bad value was supplied.
  Unreachable through the current config path (nothing generates a negative
  seed today), but a UI that accepts arbitrary integer seed input from a user
  would reach it. Needs a validation point before that UI exists, not
  necessarily in this function.

- **`tests/test_pipeline.py::test_full_render_fallback` invokes real Demucs**
  (~10s per run) despite its name implying it exercises the no-ML fallback
  path. It predates the `stub_separation` fixture added for this branch's
  other tests and was not migrated to it.

- **`test_reporter_receives_ordered_monotonic_events` cannot fail.**
  `ProgressReporter.emit` clamps its own output to be monotonic
  (`docs/architecture.md`), so this test is asserting a property the code
  under test enforces on itself — a regression in `pipeline.py`'s per-stem
  `stage_range` arithmetic that produced out-of-order *inputs* to `emit`
  would be silently absorbed by the clamp and this test would still pass.

- **`test_cancel_aborts_the_render` cancels on the first progress event.** It
  exercises the stem-loop cancel check in `pipeline.run_pipeline` but never
  reaches the per-iteration cancel check inside
  `disintegration.build_disintegrating_stream`, so that check has no direct
  test coverage.

- **`analysis._estimate_tempo` duplicates the `librosa.beat.beat_track` call**
  already made inside `_librosa_loop` for the auto-detect path — when
  detection succeeds, tempo is effectively computed twice. Only the
  explicit-loop path (`_explicit_loop`) actually needs `_estimate_tempo`
  as a separate call.

- **`MixConfig.seed` and `separation_model` carry no field metadata.** Every
  other config field has a `label`/`help`/bounds dict for `config_schema()`
  to read; these two fall through to auto-generated labels
  (`"Seed"`, `"Separation model"`) and no help text, because they sit
  directly on `MixConfig` rather than in one of the nested per-section
  dataclasses `config_schema()` was designed around.

- **`session._reference()` imports `numpy` locally**, inside the method,
  unlike every other module in this codebase, which imports `numpy` at the
  top. numpy is a required dependency, not one of the lazily-imported
  optional ones (Demucs, librosa, Rubber Band, pedalboard) that this
  codebase's graceful-degradation policy exists for — so this local import
  doesn't serve that policy, it's just inconsistent.
