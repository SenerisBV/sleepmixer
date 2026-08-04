# Architecture

This document covers the core render pipeline, the interactive layer built on
top of it (separation → loop → stretch → decay → reverb → sum → sound bed →
master, plus preview, sessions, and progress), the server that exposes all of
that over HTTP, and — as of Plan 3a, with a mixer added by Plan 3b — the
frontend that talks to that server. See `docs/project-state.md` for what each
plan actually shipped.

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
  from separation: configured, enabled stems that exist, or — only if the
  config *names* none of them — one default `StemConfig` per available stem.
  That second case
  is what happens when Demucs isn't available and separation falls back to a
  single `mix` stem; both `pipeline._plan_jobs` and `preview.render_window`
  call this same function so they cannot disagree about stem selection.

  **The two conditions are separate on purpose**, and the distinction is
  load-bearing rather than pedantic. "The config names none of these stems"
  means it has nothing to say about this song, and defaults are the only
  sensible reading. "Every stem it names is switched off" is a deliberate
  instruction, and answering it with a full default mix plays audio nobody
  asked for at a level nobody chose. Written as one condition, it did exactly
  that: unreachable until the mixer shipped per-stem Enabled checkboxes, four
  clicks away afterwards. So the function may return an empty list, and both
  callers refuse it — `render_window` raises `config.NothingToRender` (a
  `ValueError` subclass, which `POST /api/preview` turns into a 400 carrying
  the reason) rather than returning the one-frame WAV it used to, and
  `_plan_jobs` raises rather than writing half an hour of peak-normalized
  silence. Soloing a stem the render would drop takes the same door.

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

- **`cli.py`** — the `sleepmix render` / `sleepmix init-config` / `sleepmix ui`
  commands. `render` wires a `ProgressReporter` through `progress.echo_sink` so
  the terminal output is unchanged even though the pipeline now emits
  structured events instead of plain strings. `ui` starts the local server: it
  refuses a non-loopback `--host` without `--allow-remote`, imports `uvicorn`
  and `server.app` lazily so the optional extra stays optional, and passes the
  bound host into `create_app(allowed_hosts=...)`.

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

## Separation runs in a subprocess, so it can be killed

`demucs.apply_model` is a single opaque call: it returns when it returns, and
nothing inside it ever looks at a cancel token. Before this branch, "cancel a
running separation" set a flag nothing would read until that call finished —
which meant it did nothing at all, in practice, for the file long enough to
matter. That is the incident this branch exists to fix: a seventy-minute file,
imported by accident, that suspended the server (`Ctrl-Z`, not a kill) rather
than dying when the operator tried to stop it, and was found still holding
6.2 GB resident.

`separation_process.run_separation` spawns `python -m
sleepmix.separation_worker <input> <model> <cache_dir>` as a child process and
owns exactly three things: forwarding its progress, killing it on request, and
being exact about how it ended. **The handoff between parent and child is the
stem cache that already existed** for `separate_detailed` — the worker writes
it, the parent reads it back with `_load_cache`, and no audio array ever
crosses the process boundary. That is deliberate, not incidental: a
multi-hundred-megabyte-per-stem buffer would be slower to pickle through a pipe
than the disk round-trip it replaces, and the cache was going to exist either
way.

**The phase protocol is three flushed lines on stdout.**
`separation_worker._phase` prints `sleepmix-phase <fraction> <message>` at
three fixed points — "Loading the model" (0.05), "Separating stems" (0.15),
"Writing stems" (0.90) — flushed per line rather than buffered, because a
buffered phase is a progress bar that sits still for the whole length of a
separation and then jumps straight to done. The parent reads these on a
background thread (`_pump`, feeding a `queue.Queue`) so its own poll loop never
blocks waiting on the pipe. A second background thread (`_StderrTail`) drains
stderr for an unrelated reason: torch and demucs both write warnings there, an
OS pipe has a bounded buffer, and a child that fills it with nobody reading is
a separation that hangs rather than one that finishes or fails — silently, with
no error anywhere to explain why.

**The three ways a child can end map to three different outcomes, and
conflating any two of them would be silent.**

1. **Cancelled.** The parent's poll loop notices the token is set, sends
   `SIGTERM`, waits, and escalates to `SIGKILL` if the child ignores it (a
   torch process declining to die tidily is not a reason to keep the operator
   waiting) — then raises `Cancelled`, **unconditionally, and checked before
   either the exit code or the cache**. That ordering is what
   `test_cancelling_after_the_cache_is_already_written_still_raises` pins down:
   a child that reached `_write_cache` a moment before it was killed — the
   worst case in this task's own table — must not have that cache read back as
   a quiet success just because the bytes happen to be sitting on disk. The
   caller (`server/api/songs.py`'s `separate_song`) catches `Cancelled` and
   puts the song back to `pending` with no reason recorded: the operator asked
   to stop, and nothing about the song should read as broken.
2. **Crashed.** A nonzero exit code, or a clean exit that wrote no stems at
   all (`test_a_nonzero_exit_is_a_failure_not_a_fallback`,
   `test_exiting_cleanly_without_writing_a_cache_is_a_failure`), both raise
   `SeparationFailed`, and the caller writes `separation_status="failed"` with
   the reason. An external OOM kill falls into this case too — from the
   parent's point of view a killed child looks the same whether the killer was
   a cancel or the kernel, and the only thing that tells them apart is the
   cancel token: if it was never set, the death was not requested, and it must
   not read as anything gentler than a failure.
3. **Demucs genuinely isn't installed.** This is decided entirely *inside* the
   child, before the parent ever sees an exit code: `separate_detailed`'s own
   `except Exception` around the `_demucs_separate` call is what answers "is
   Demucs importable" by writing the whole song as one `mix` stem plus a
   fallback marker, and exiting 0 having done so. It is the right answer to
   that one question, and it is answered nowhere else — the parent's own
   exception handling never re-derives "demucs isn't installed" from a process
   outcome; it only ever sees exit code and cache state.

**Why conflating them would be silent.** `separate_detailed`'s fallback exists
to answer one question well, and answering it well is exactly what makes it
the wrong answer to the other two: a killed child taking that path would
quietly convert the song to a one-stem `mix` that then renders and plays
without complaining, discarding every per-stem decay setting the operator had
already tuned, with nothing on screen to say why the stems are suddenly gone.
That is why `separation_process.py` exists as its own module with its own
interpretation of a process outcome, rather than folding into
`separation.py`'s existing broad catch — process-level outcomes (cancelled,
crashed) are decided by the parent from the child's returncode and the cancel
token; only the "is the dependency importable" question is left to the
child's own catch, because that is the one question a broad catch answers
correctly.

`tests/test_separation_process.py`'s slow test builds a stub worker that
writes a one-stem fallback cache and then sleeps, cancels it mid-flight, and
confirms `Cancelled` is raised with the child reaped (`returncode -15`) and no
result returned — the failure taxonomy holding on the path this task's own
review ranked as worst. This task's own manual verification reproduced the
same shape against the real worker and a real 246.6 s track: cancelling a
genuine Demucs run partway through (`fraction=0.15`, "Separating stems") left
the song back at `pending` with `separation_reason: null`, no worker process
still running, and — checked directly against the cache directory — nothing
in it at all, not even a staging directory. `_write_cache`'s per-key sweep
(below) exists for the case where a kill lands mid-write; this run's kill
landed before any write started, so there was nothing to sweep.

## The stem cache is written atomically, and that is what makes killing the writer safe

`separation._write_cache` builds the fallback marker (if any) and every stem
into a sibling staging directory (`tempfile.mkdtemp(prefix=f".{key}.",
dir=cache_dir)`) and renames the whole thing into place — `os.replace` twice,
old cache to a doomed name and staging to the real one — only once everything
is on disk. An interrupted write, from any cause, leaves either the previous
complete cache or no cache at all; it can never leave a subset of stems, and
it can never leave a marker with no stems behind it either, because the marker
and the stems are written into the same staging directory and renamed
together as one unit.

**This used to be two separate writes, in a deliberately chosen order, and the
reasoning behind that order is worth keeping even though the order itself is
gone.** Before this branch, the fallback marker was written first and the
stems second, directly into the final cache directory, specifically so that a
failure between them left a stale marker with no stems (which `_load_cache`
correctly treats as a miss and recomputes) rather than stems with an
unrecorded fallback (which would have read as a properly separated song that
happened to only have one stem). That was the best available ordering while
the write could not be made atomic — the two-step version has no atomic
"finish" to interrupt, only "wrote the marker" and "wrote the stems", so *some*
ordering had to be chosen and defended. It stopped being the relevant question
the moment the write became a single staging-directory rename: there is no
window between "the marker exists" and "the stems exist" for a crash to land
in, because both are written to a location nothing else looks at until the
rename makes them appear together, atomically, or not at all. The old ordering
mattered only because the write used to lack exactly the property this one
was built to have.

A killed writer — which this branch's subprocess separation makes routine
rather than a rare crash — can still leave an orphaned staging directory
behind, with no process left to clean it up: a full stem set, hundreds of
megabytes. `_write_cache` sweeps these itself, at the top of its own run,
scoped to the one cache key it is about to write (`prefix = f".{key}."`) —
sweeping the whole cache directory would race a concurrent write of a
*different* song, but a single worker only ever has one write in flight for a
given key at a time, so a leftover staging directory under that key can only
be an orphan from an earlier, killed attempt at the same separation.

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
`separate()` returns (`pipeline.py:50-51`), once after the stem and sound-bed
sections finish and before mastering begins (`pipeline.py:78-79`), and inside
`build_disintegrating_stream`'s per-iteration loop, reached via `cancel`
threaded through `_process_stem` (`pipeline.py:70`, `pipeline.py:104`) into
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

## Matching a preview's loudness to the render

A preview window is one loop iteration, rendered on its own. A full render is
peak-normalized once, over the entire stream, at the very end
(`pipeline.run_pipeline`'s closing `normalize_peak(mix, config.output.peak_db)`).
Those are two different operations, and running them independently means a
preview of, say, an already-half-decayed iteration gets normalized to fill the
same headroom as the render's single loudest moment, rather than sitting at
the level it would actually occupy relative to the rest of the mix. Concretely:
without a correction, a preview plays about 4 dB above the render it
represents — and because louder reads as *less decayed*, that's exactly the
judgement a preview exists to let someone make correctly. The purity property
that makes previewing cheap (see above) says nothing about loudness; it only
guarantees a window's *samples* match a render's, before normalization ever
enters the picture.

This was found by listening during development, not by a test.
`render_window`'s bit-identity guarantee (`tests/test_preview.py`) compares a
preview window against the corresponding render iteration pre-reverb and
pre-master, so it kept passing the entire time this was wrong — the
divergence only appears at the whole-stream normalization step, which no
per-window test exercises by construction.

The fix, `preview.master_gain`, measures a single gain factor and applies it
uniformly to every window rather than normalizing each one on its own. It can,
because decay only removes energy — spectral holes, dropouts, amplitude fade,
and a rising noise floor all pull a stem's level down or leave it unchanged,
never up — so the peak across the whole arc falls monotonically, and the
loudest window `render_window` can produce is always iteration 0
(`progress=0.0`), where `apply_decay` is a pure passthrough that no decay
setting can move. (Note the careful phrasing: iteration 0 is the loudest
*window*, and it is **not** the render's loudest moment. `_apply_fades` runs
before `normalize_peak` and `fade_in_s` defaults to 8 s, so the render's peak
lands after the fade-in completes. See the four-part level-matching entry in
`docs/project-state.md`; this is the largest of the remaining gaps, measured at
−1.82 dB.) `master_gain` renders exactly that one window
(`render_window(session, 0.0, reverb=<flag>, master=False)`), measures its
peak, and computes the ratio to `db_to_amp(config.output.peak_db)` — the same
target `normalize_peak` aims for on a real render. That single factor, memoized
on the session (`RenderSession.master_gain`), is what
`render_window(..., master=True)` (the default) applies to every subsequent
preview regardless of where in the arc it sits. Applying one factor everywhere
rather than normalizing per window is what preserves the arc: later windows
end up quieter because they genuinely contain less energy, not because each
one was independently pushed back up to full scale, which would flatten the
whole point of the decay.

**The factor is calibrated per signal path, so `RenderSession.master_gain` is a
dict keyed by the `reverb` flag rather than a single float.** Reverb changes
the peak the calibration window measures, and a factor measured wet then
applied to a `reverb=False` window mis-levels it — measured at the default
reverb config, a dry mastered preview sat at 0.6922, −3.20 dB. That is the same
defect this section describes fixing, pointing the other way: quieter reads as
*more* decayed, so a dry solo would look further through the arc than it is.
`render_window` passes its own `reverb` argument into `master_gain`, and
`update_config` clears the whole dict exactly as it previously cleared the
single value. A `reverb=True` mastered window is the level `run_pipeline` would
produce; a `reverb=False` one is a level-matched view of the dry path, not a
simulation of any render, since every real render applies reverb.

`RenderSession._master_key` decides when the memoized factor is stale.
Deliberately excluded: every stem's `decay` settings, `soundbed`, and `seed` —
none of them can move a number measured at progress 0. Included: `reverb`,
`output.peak_db`, `output.channels`, and each stem's `enabled`/`gain_db`/
`reverb_send` — everything that actually changes what iteration 0 sounds like.
Getting this split wrong in either direction was caught twice during this
plan's own review: once from a stem's `enabled` flag being left off the key
while affecting the gain anyway, and once from the session registry calling
`update_config` on every request and clearing the memo unconditionally,
recomputing it — a second window render — on every single preview.

After the fix, a direct RMS measurement against a real render at a mid-arc
window landed within +0.005 dB — effectively exact. Separately, and more
convincingly because it doesn't share the developer's own instrumented test,
listening files were regenerated and re-measured by ear: the point in the
render where the preview's loudness best matched moved from 0:20 to 4:45,
which is where an independently-run spectral match had already put it (4:55).
Before the fix, the two methods disagreed by over four minutes on a
twenty-five-minute mix; after it, they agree to within ten seconds.

This does not close every gap of the same shape. Four things still contribute
to a render's final peak that the calibration window never sees, and they are
recorded — with measured magnitudes, in order of size — in
`docs/project-state.md`. Briefly: the fade-in, which attenuates exactly the
region iteration 0 occupies (−1.82 dB at the defaults, and the reason the
render's loudest moment is not iteration 0); the inter-iteration crossfade,
whose overlap can sum above a single iteration's peak (+0.37 dB on the dry
path); `output.sample_rate`'s absence from `_master_key`, small in level but
unconditional as a cache bug; and the sound bed, which `render_window` never
mixes in (+0.03 dB at the default level, −0.05 dB even at −6 dB — the stems get
scaled down by very nearly the factor the bed pushed the peak up, so it
mostly cancels). The sound bed was previously described here and in
`project-state.md` as the most important of these; measurement says it is the
least, by roughly thirty-five times.

## Jobs, progress, and sessions

Five design choices in `sleepmix/server/jobs.py`, `sessions.py`, and
`api/preview.py` look arbitrary in isolation and are not.

**One worker, deliberately.** `JobManager` defaults to
`ThreadPoolExecutor(max_workers=1)`. A render is CPU-bound numpy running for
minutes over hundreds of loop iterations; two running at once would halve
each other's throughput and double peak memory, in exchange for nothing —
this is a tool one person uses at a time, not a multi-tenant service. Starting
a second render while one is in flight does not fail or block the request:
`submit` always accepts the job, creates its row, and returns immediately. The
second job simply queues behind the pool's one worker and stays at whatever
status `Job` starts in (`"queued"`) until the first job's thread frees up —
nothing runs it in parallel, and nothing makes it wait longer than the first
job actually takes.

**Progress crosses the thread boundary through `call_soon_threadsafe`, and
that is the only safe way to do it.** A job's `fn` runs on the pool's worker
thread, not the event loop; every progress event it reports flows through
`ProgressReporter` into `JobManager._on_event` → `_update` → `_publish`, which
ends in `loop.call_soon_threadsafe(queue.put_nowait, snapshot)`
(`jobs.py:153-165`). `asyncio.Queue` is not thread-safe — nothing about it
guards against two threads mutating its internal deque at once — and
`call_soon_threadsafe` is the one API asyncio provides for scheduling a
callback to run *on the loop*, from any other thread, safely. Calling
`queue.put_nowait` directly from the worker thread would race the event
loop's own bookkeeping of that same queue and corrupt it; `subscribe()`'s own
unguarded `put_nowait` for the late-subscriber snapshot (below) is safe for
the opposite reason — it never runs anywhere but the loop thread, which
`server/api/jobs.py`'s `stream_job` says explicitly at the call site.

**A late subscriber gets an immediate snapshot because nothing else will ever
wake it.** `JobManager.subscribe()` checks whether the job is already in a
`TERMINAL_STATUSES` state, and if so, pushes the job's current snapshot onto
the new queue right there, before returning it. Without this, a client that
opens `/api/jobs/{id}/events` after the render already finished — a page
refresh, a second tab, a reconnect — would await a queue that nothing will
ever populate again, because `_update` (the only thing that publishes) is
only ever called from within `_run`, which by then has already returned. The
snapshot turns "connected too late" into "sees the outcome immediately"
instead of "hangs forever."

**The session registry is capped at two because a session is expensive to
hold, not expensive to build twice.** `SessionRegistry(max_sessions=2)` keeps
warm `RenderSession`s so consecutive preview requests for the *same* song
skip re-separating and re-stretching; a session holds every stem decoded in
memory — roughly fifty megabytes per stem for a five-minute stereo track,
more once stretched loops are cached alongside the originals. `get()` moves
the just-used entry to the end of an `OrderedDict` and, once the registry
holds more than `max_sessions`, evicts from the *other* end
(`popitem(last=False)`) — the least-recently-used song, never the one just
requested. Two is enough to A/B two songs at once without the process's
memory growing without bound as someone works through a library.

**A warm session needs a second lock, because the registry's own protects only
the dictionary.** `SessionRegistry._lock` makes insert, LRU reorder and
eviction atomic, and guarantees two callers asking for one song id get one
object. It guarantees nothing beyond that — and specifically it is not held
across any expensive work: `RenderSession.__init__` does nothing, `stems()` is
lazy, and the first `prepared_loop` call that actually separates runs long
after `get` returned. (The class docstring claimed the opposite for a while —
that `get` "builds a new session while holding `self._lock`, so two concurrent
requests for different songs serialize." That was false, and false in the most
expensive possible way: it is exactly what would convince a reader the
concurrency question was already handled.)

It matters because `POST /api/preview` is a sync `def` route, so FastAPI runs
it in AnyIO's threadpool — several overlapping previews of one song really are
several threads on one `RenderSession`, which is precisely what a scrubber
drag produces. Meanwhile `get` calls `update_config` on every request, and
that clears `_prepared`. The interleaving: thread A is inside `prepared_loop`,
has found the stem present, and is about to index `_prepared`; thread B's
`update_config` clears it; A raises `KeyError` and the preview 500s. The
silent variant is worse — A reads `session.config` under one config and renders
against another's stretched loop, producing a window built from two configs
with no error at all.

`SessionRegistry.session_for(...)` is the fix: a context manager that holds a
per-song `RLock` across the *whole* use — resolving the session, reading its
config, and rendering — not just the lookup. `/api/preview` uses it; `get()`
remains for callers that only need the object, such as `sessions.discard`.
The locks are keyed by song id and dropped only in `clear()`, never on
eviction: a thread can be holding one while another evicts the session, and
releasing it there would hand the next arrival a fresh lock and no mutual
exclusion at all. That costs a few dozen bytes per song and avoids reference
counting. `tests/test_sessions.py` drives six threads at `render_window` with
five different tempos and asserts each returned window's frame count matches
the tempo that thread asked for — the frame count being a fingerprint of which
config a window was actually built from, which is what makes the silent
failure visible rather than merely improbable.

**A preview returns raw WAV bytes because nothing about it should touch
disk, and Elm cannot carry the bytes anyway.** `POST /api/preview` calls
`encode_wav` and returns the result directly as an `audio/wav` response body,
never `save_audio`-ing anything to a path first. A preview is expected to
fire on every slider drag; writing a temporary file per request would be both
slower and a cleanup problem with no upside, since nothing needs the bytes to
persist past the one response that carries them. The bytes-not-URL choice is
also forced from the other direction: Elm has no way to receive binary data
over a port, so a small JavaScript port fetches `/api/preview` directly and
hands the decoded buffer to the Web Audio API, while Elm only ever sends the
parameters that produced it. A URL would still need that same JS-side fetch
to turn into audio, so returning one would add a round trip for no benefit.

## Where data lives

`paths.data_dir()` — a per-user location outside the project directory — is
the only place sleepmix writes app data: the separation cache under
`paths.cache_dir()`, and, since this plan, the library database at
`paths.data_dir() / "library.db"` (`server/store.py`). `SLEEPMIX_DATA_DIR`
overrides it entirely; the test suite sets this to a fresh `tmp_path` for
every test via the autouse `isolated_data_dir` fixture in `tests/conftest.py`,
so no test run touches a real cache or a real library. Nothing else — no
config, no rendered output — is written outside paths the caller explicitly
asks for (`--output`, `save_audio`'s destination).

## The server

`sleepmix/server/` is the part of this plan that makes the pipeline reachable
over HTTP. It is deliberately thin: everything it does is either call into a
module documented above or persist a record of having done so.

**The server holds no business logic.** `server/api/songs.py` decodes audio
with `audio.load_audio` and summarizes it with `peaks.compute_peaks` — both
pre-existing pipeline modules — rather than reimplementing anything; the only
code specific to the route is turning a `Store` row into a response and a bad
path into an `HTTPException`. `server/api/schema.py`'s entire body is one call
to `config.config_schema()`. The payoff is that the pipeline stays usable
identically from the CLI, from Python, and from HTTP, so a bug fixed once is
fixed everywhere. The routes still carry behaviour of their own and are tested
for it directly (`tests/test_api_songs.py`): which failure is a 400 and which
is a 404, the `MAX_PEAK_BUCKETS` bound, the "file has moved" case. Thin is not
the same as trivial.

`GET /api/songs/{song_id}/loop` is Plan 3b's addition to this router and
follows the same pattern: it decodes the file with `audio.load_audio` and
calls `analysis.find_loop` directly, the same function `RenderSession` and
`run_pipeline` both call, so the region a mixer draws cannot disagree with
the one a render would actually use. It runs on the *whole* file rather than
on separated stems, which is deliberate — it answers before separation has
happened and needs no warm `RenderSession` — and it accepts optional
`start_s`/`end_s` query parameters that echo a region back with a tempo
rather than re-detecting it, which is what the mixer sends once loop handles
have been dragged (see `docs/project-state.md`; there are no handles on the
waveform yet, only schema-generated number fields for those two config
values). **It has no cache**, unlike everything else this section describes:
every call re-decodes the file and re-runs beat tracking, and the mixer now
calls it more often than anything before this plan did — on opening a song
and again on each of the two config edits it watches. This was identified
during this plan's second task and deliberately left unfixed; it is recorded
as a known weakness in `docs/project-state.md` rather than repeated here.

**`create_app` is a factory, not a module-level `app`.** A module-level
`FastAPI()` instance would be process-global — every test importing the
server module would share one `Store` and one on-disk database. `create_app`
takes an optional `store: Store | None`, and `lifespan` puts whichever store
is in play on `app.state.store`, where every route reaches it via
`request.app.state.store`. The real entry point, `cli.py`'s `ui` command,
calls `create_app()` with no store and gets the default.

Isolation in tests comes from a different direction than the `store=`
parameter: `tests/conftest.py`'s autouse `isolated_data_dir` fixture points
`SLEEPMIX_DATA_DIR` at a fresh `tmp_path` for *every* test, so the default
`Store()` a bare `create_app()` opens already lands in a throwaway directory.
Most server tests therefore just use `TestClient(create_app())`. Nothing in
the codebase uses an in-memory SQLite database; the store is always a file.

`lifespan` closes the store **only if it opened it** (`owned = store is None`).
A store handed in by the caller is borrowed, not owned — closing it on
shutdown would hand back a dead connection, and a second `TestClient` context
over the same app would rebind it and raise `sqlite3.ProgrammingError`. That
is what `test_an_injected_store_outlives_the_app` pins down.

**A `running` separation row at startup is definitionally orphaned, and
`lifespan` now says so before anything else runs.** `separation_status` moves
to `"running"` before a separation job starts and is cleared only by a
terminal status or one of `separate_song`'s two exception handlers — none of
which fire if the process itself dies. `JobManager` is in-memory, so a row
still reading `"running"` when a fresh `lifespan` starts has no job behind it
and never will: the previous process was killed or suspended
mid-separation. `Store.reconcile_orphaned_separations()` resets every such row
to `"pending"` (clearing `separation_reason` too) and is called immediately
after `app.state.store` is set, before the job manager or session registry
exist — a song that would otherwise claim to separate forever becomes
retryable from the interface again on the very next load. This was found in
practice, not by reasoning about it in the abstract: two rows were observed
stranded at `running` after a `Ctrl-Z`, which suspends a process rather than
killing it and looks identical to a clean exit from the row's point of view.

**`fastapi`/`uvicorn` are the `ui` optional extra** (`pyproject.toml`), not a
core dependency — the same policy that keeps Demucs, librosa, and Rubber Band
optional applies here: nothing beyond `numpy`/`scipy`/`soundfile`/`pedalboard`
is needed for `import sleepmix` or the CLI's `render`/`init-config` commands
to work, and a server most people never run shouldn't change that.
`cli.py`'s `ui` command wraps `import uvicorn` in a `try/except ImportError`
and raises a `SystemExit` pointing at `pip install "sleepmix[ui]"` if it's
missing. That guard has a gap, recorded in `docs/project-state.md`: the
following `from .server.app import create_app`, which pulls in `fastapi`, sits
outside the `try`, so an install with `uvicorn` present but `fastapi` missing
shows a raw `ImportError` traceback instead of the same hint.

**The store's schema (`server/store.py`) is three flat tables** — `songs`,
`presets`, `renders` — behind stdlib `sqlite3`, no ORM. `songs` carries
`path`, `title`, `duration_s`, `sample_rate`, `separation_status` /
`separation_reason` (both written by `POST /api/songs/{id}/separate` — see
"Jobs, progress, and sessions"; the status moves `pending → running →
done`/`fallback`/`failed`, and back to `pending` on a cancel, so a cancelled
run does not leave the row claiming to be broken), and `stems`. `presets`
and `renders` each carry a `config` column that stores a whole `MixConfig` as
a JSON blob rather than exploding it into one column per field. This is
deliberate: `MixConfig` already round-trips through `dataclasses.asdict` and
back (that's what `config_schema()` and YAML loading both rely on), so
storing its dict form costs nothing extra, while a normalized schema would
need a migration every time a decay parameter is added or renamed — which,
given how young this config surface still is, would be often. The cost is
that nothing can filter or sort renders by an individual config field in SQL;
nothing here needs to yet.

**Importing a song registers a path; it does not copy the file.** This is a
local tool pointed at the operator's own music library — copying
potentially gigabyte-scale files into an app-data directory on every import
would double disk usage for no benefit the operator asked for. The
consequence is in `server/api/songs.py`: if the file at that path is later
moved, renamed, or deleted, `import_song` already succeeded and the row
already exists, so the failure surfaces on the *next* access instead —
`GET /api/songs/{id}/peaks` checks `os.path.isfile` itself and returns a 404
with an explicit "it has moved or been deleted" message rather than letting
`load_audio` raise something opaque. Nothing re-links or repairs the entry;
the row just keeps 404ing until the operator re-imports it or fixes the path by
hand. `GET /peaks`, `POST /api/preview` and `POST /api/renders` all now make
the same `os.path.isfile` check and return the same message, so the failure
reads identically wherever it is first hit.

**The warm-up (`server/warmup.py`) exists because librosa's first call in a
process is slow and every later call is fast.** librosa leans on numba, which
JIT-compiles on first use; during Plan 1's development, one cold first call
exceeded a two-minute test timeout while the very next call in the same
process took under a second (`docs/project-state.md`). A CLI eats that cost
once per invocation and it's tolerable; a server that stays up for a session
should not make a user's first click pay it. `app.py`'s `lifespan` kicks off
`warm_analysis` via `asyncio.create_task(asyncio.to_thread(...))` so it runs
off the event loop — the point is that `/api/health` and the static shell can
already respond while a beat-track call is warming numba in the background —
and `is_warm()` is surfaced on `/api/health` so a caller can tell whether
that's finished. It is silent and best-effort if librosa isn't installed at
all, matching the rest of the codebase's graceful-degradation policy.

## The frontend (Plan 3a)

`sleepmix/static/index.html` now serves a compiled [Elm](https://elm-lang.org/)
application (`ui/src/Main.elm`) instead of the placeholder page described
above. See `ui/README.md` for how to build, develop, and test it; this section
is about the design choices behind it.

**Why Elm.** Most of this codebase, this frontend included, is written by an
agent. Elm's compiler turns a whole class of mistake that would otherwise be
a runtime problem — a renamed field, an unhandled case in a union type, a
decoder that no longer matches what the server sends — into a build failure.
The alternative failure mode, in a dynamically-typed frontend, is a screen
that renders blank and says nothing, which is far harder for an agent (or
anyone) to notice than a compiler error. `Main.elm`'s own module docstring
states this plainly as the reason it exists.

**Where Elm stops, and why.** `elm/http` has no server-sent-events support, so
Elm cannot open an `EventSource` itself, and ports — the only channel in or
out of an Elm program — are asynchronous and JSON-only: nothing but a decoded
JSON value crosses that boundary, in either direction. `ui/ports/events.js`
therefore owns the actual `EventSource` connection to
`/api/jobs/{id}/events`; `Main.elm` sends a job id out over a `watchJob` port
and receives already-parsed job events back over a `jobEvent` port, decoded
immediately into `Api.Job` by `Decode.decodeValue Api.job`. A decode failure
there surfaces as a `Result Decode.Error` for `update` to handle, not a crash.
Elm never touches audio bytes, and the same shape now also covers preview
playback: `ui/ports/audio.js` fetches `POST /api/preview`, decodes the
response with the Web Audio API, and loops it.

**Why the decision to send a preview lives in Elm and not in the port.**
`ui/src/Preview.elm` decides *when* to ask for a preview; `ui/ports/audio.js`
only carries out what it decides. That split could have gone either way —
nothing about `fetch` or `decodeAudioData` requires JavaScript to be dumb —
but only one side of it can be reached by `elm-test`, and the decision is the
part of this path most worth getting right, because getting it wrong is
silent: a coalescing bug fires extra renders against a server that queues
them, and nobody watching the screen would see anything wrong until the
scrubber started lagging seconds behind the pointer. `audio.js`'s own header
comment states the same division from the other side: it holds two pieces of
state, the playing source and the in-flight fetch, and "decides nothing" —
"a queue here would be a bug."

The decision `Preview.elm` exists to make is *when to coalesce*.
`POST /api/preview` serializes per song — `SessionRegistry.session_for` holds
one lock across the whole request — and the very first request against a
song with nothing cached anywhere stacks three separate costs into that one
HTTP call: **separating the stems** (`separation.py`, Demucs, minutes, paid
once ever per `(file, model)` and cached to disk under `paths.cache_dir()`
after that), **building the session** (`session.py`'s `RenderSession` —
finding the loop and time-stretching every stem, paid once per song per
server process because `SessionRegistry` then keeps the built session warm),
and **rendering the requested window** itself (`preview.render_window` — one
decayed, reverbed iteration, tens of milliseconds per stem). Coalescing has
to guard against the sum of all three, not just the last one.

Two independent measurements of that sum exist, on two different tracks, and
they agree once the difference in track length is accounted for rather than
contradicting each other. Plan 2b's own verification measured it at **117 s**
cold, **73 ms** warm, against a 2:43 file (`nackmandela.mp3`) with nothing
cached at all — separation included, per that task's own report
(`.superpowers/sdd/2026-08-04-interactive-server/final-fix-report.md`). This
plan's own Task 7 repeated the same experiment — cache cleared, server
restarted, a fresh request against the same song with no separation on
disk — on a different, 4:06 file, and measured **180.55 s** cold and
**97–340 ms** warm. 117 s scaled by the ~1.51× difference in track length
(246.6 s ÷ 162.8 s) predicts ≈177 s, close to the 180.55 s actually measured;
the two figures corroborate each other rather than disagreeing. (The warm
figure's own spread, 97 ms at progress 0 up to ~340 ms deeper into the arc,
is `preview._reverbed_window`: iteration 0 has no preceding iteration to
supply reverb context, so it costs one `decayed_iteration` call per stem,
while every later iteration costs two — the context and the window itself.)
Track length and hardware will move the exact numbers; what carries across
both measurements is the *ratio* — three to four orders of magnitude between
the first request against a song and every one after it — which is the
argument coalescing actually rests on. A scrubber drag fires a control-change
event on roughly every animation frame, so one request per event would queue
dozens of renders behind each other, each pinning one of FastAPI's threadpool
threads for the render ahead of it rather than its own. `Preview.State` —
`Cold | Warming | Idle | InFlight Params | Queued Params` — allows at most one request in
flight and at most one waiting; a request arriving while one is already in
flight *replaces* whatever was queued rather than joining a line, because the
position the user has already scrubbed past is worthless by the time the
server would get to it. `ui/tests/PreviewTest.elm` asserts the resulting
property directly: twenty scrubber positions fired during one drag collapse
into a single emitted request, and the latest position is the one that wins.
`Cold` and `Warming` exist because coalescing isn't enough on their own to
protect the *first* request: something still has to make that opening call,
since it is also what calibrates `preview.master_gain` for every preview that
follows, and `request` refuses to send anything while `Cold`. `Preview.warm`
is the one function that does — see "Entering the mixer costs one long
request and says so" in `ui/README.md` for the reasoning about that specific
request.

**A full render, measured beside those same preview figures.** All of the
above is about the cost of *entering* the mixer; nobody had measured the cost
of the render the mixer's own button starts. Task 9's own verification did,
against a track measured at 246.6 s — coincidentally (or not; the file is not
named in either report) the same length as the one this section's 180.55 s
cold-preview figure was measured on — with its stems already separated and
cached, so, unlike that cold-preview number, this pays nothing for Demucs.
`POST /api/renders`
at the default `output.duration_min` (20 minutes, i.e. a 1200 s mix from a
246.6 s source) was watched start to finish over its own `GET
/api/jobs/{id}/events` stream and finished in **13.6 s** wall-clock, corroborated
by a second run's file `Last-Modified` timestamp against its job's
`created_at` (**11.0 s**). Both are three orders of magnitude below the
180.55 s cold-preview figure two paragraphs up, and that gap is not a
coincidence: a render pays for loop detection and per-stem time-stretching
exactly once regardless of the output length, then iterates
`build_disintegrating_stream` roughly seventy times (a ~17.6 s loop filling
1200 s) at the tens-of-milliseconds-per-stem cost `preview.render_window`
already established — there is no separation call in this path at all once
the cache is warm, which every render started from an already-open mixer's
Render button is. See `docs/project-state.md`'s note on `Warn.forSource` for
what this measurement implies about that warning's own threshold, which keys
on source length rather than the output length that actually drives a
render's cost.

**Gapless swapping at loop boundaries.** A preview buffer is one loop
iteration, played on a loop; changing a control mid-playback produces a new
buffer that has to replace the old one without an audible seam. `audio.js`'s
`nextBoundary` computes how many multiples of the *currently playing*
buffer's duration have elapsed since it started, and returns the next one;
`play` schedules the new `AudioBufferSourceNode` to start exactly there and
stops the old one at the same instant via `Web Audio`'s own sample-accurate
`start(when)`/`stop(when)`. The swap therefore always lands on the point the
old buffer would have looped anyway, not on whenever the fetch happened to
finish — a decay control dragged mid-loop hears the current iteration finish
before the next one begins, rather than a cut to a different point in the
arc partway through a cycle, which would read as a skip rather than a
change.

**Why decoders are strict.** `ui/src/Api.elm` is the seam between an untyped
HTTP response and a typed Elm value, and its own docstring calls this out
directly: decoding is deliberately strict rather than permissive. Both status
enums it decodes — `separation_status` on a song, `status` on a job — read a
string field and `Decode.andThen` into a closed union of known values; an
unrecognised string hits `Decode.fail` with a message naming the unexpected
value, rather than falling back to some default variant. Concretely, if the
server started reporting a `separation_status` this build of the frontend
doesn't know about (plausible if the Python and Elm halves of a change ship
on different schedules), the song detail view shows a decode error instead of
silently treating that song as, say, `NotSeparated` — wrong is loud rather
than wrong and quiet. This trade only makes sense because the frontend and
the server it talks to are versioned and shipped together out of one repo; it
would be the wrong default for a public API serving clients it doesn't
control.

**Why the waveform is SVG, not canvas.** `ui/src/Waveform.elm`'s docstring
gives the reasoning directly: a `<canvas>` would mean escaping Elm's virtual
DOM entirely and managing pixels through a port — every draw call would need
to cross the same JSON-only boundary described above, for data (a few hundred
peak pairs) that doesn't need to. The interaction the waveform was chosen to
leave room for — loop-region drag handles — would be just mouse events mapped
to `Msg` values, which is precisely the state machine Elm's `Html.Events`
models well without any port at all. SVG elements are ordinary Elm values
diffed by the virtual DOM like any other node, and a few thousand `rect`
elements (`peakBuckets = 200` today, so 200 of them, per `Main.elm`) is well
within what a browser draws comfortably without needing canvas's raw pixel
throughput.

*Correction:* an earlier version of this paragraph said Plan 3b delivered
those drag handles. It did not, and the claim was never true — `Waveform.elm`
draws the loop region (`loopRegion`, fed by `GET /api/songs/{id}/loop`) as a
static shaded rectangle with a tempo caption; nothing in `ui/src` attaches a
mouse handler to it. `config.loop.start_s`/`end_s` are editable in the mixer
today only as ordinary schema-generated typed number boxes in the Loop
section (`Config.elm`'s note on why those two fields default to absent
rather than `0.0` describes the same fields from the config side), not by
dragging on the waveform. The SVG-over-canvas reasoning above is unaffected —
it was always about what the choice would cost *if* that interaction were
built — but nothing in this branch builds it.

**Schema-driven controls, and what an unknown field type does.**
`GET /api/schema` is `config.config_schema()` (documented above, under
`config.py`) serialized to JSON — label, bounds, step, unit, choices, and
help text, per field. `ui/src/Schema.elm` decodes that response into a closed
union, `Field = FloatField | IntField | BoolField | TextField |
IntChoiceField | StringChoiceField`, and `ui/src/Page/Mixer.elm` turns each
case into a control by one rule: `min`/`max`/`step` present → a slider,
`choices` present → a select, a bool → a checkbox, anything else → a typed
box carrying whatever bounds the schema does state. `ui/src/Config.elm` holds
the values in dictionaries keyed by whatever the server called the field, and
puts them back into the nesting `MixConfig.from_dict` expects. `Config.elm`
names no config parameter at all, with three structural exceptions
`Config.elm`'s own docstring lists (the `stem`/`stem_decay` sections describe
elements of a list rather than global settings; a stem's `name` identifies
its row rather than being a value you pick; `stems` itself is a list, which
the schema does not describe at all). `Page/Mixer.elm` names a handful, each
defended in its own docstring where it appears: `separation_model`, which it
removes from the generated controls because changing it costs a Demucs run
rather than a re-render; `output`/`duration_min`, to say how far into the
finished mix the scrubber is; `loop`/`start_s`/`end_s`, the two fields the
loop endpoint can actually take an override for; and the section names that
get a `sectionNote`. None of them is a *control* — every control on the screen
is still generated — so adding a field to a dataclass in
`sleepmix/config.py` still puts a working, bounded, round-tripping control in
the mixer with no Elm change. This is the same drift-proofing `plan_stem_configs`
gives the CLI and the server, applied one layer further out: a hand-written
Elm control set could name a field the schema stopped emitting, or fail to
notice a new one, the same way a hard-coded stem list could disagree with
what separation actually returned.

The union being *closed* is what makes an unknown field type loud rather than
quiet. `Schema.field`'s decoder dispatches on the server's `"type"` string —
`"float"`, `"int"`, `"bool"`, `"str"`, each further split on whether
`"choices"` is present — and a type it doesn't recognise hits
`Decode.fail ("unknown config field type: " ++ other)` rather than skipping
the field or rendering some generic fallback. Because `Schema.decoder` reaches
that one field through `Decode.dict field`, and an Elm decoder either fully
succeeds or fully fails, one field of a type this build doesn't recognise
fails the *entire* `/api/schema` decode — not just that field. `Main.elm`
handles it exactly like any other failed request: `GotSchema (Err err)` sets
`settings = SettingsUnavailable (httpErrorToString err)`, so the mixer entry
point shows a plain error naming what went wrong instead of a schema with one
quietly-missing row. `Schema.elm`'s own docstring states the reasoning
directly: "a field type this application cannot render fails the decode
loudly instead of rendering nothing. That is most of the reason the project
chose Elm." A dynamically-typed frontend handed the same unrecognised field
would most likely just drop it while decoding everything else — the mixer
would open looking complete, with one fewer control than the server actually
has fields for, and nothing in the browser console to explain the gap. The
Elm failure mode is uglier to look at and strictly better to debug: an error
message naming the exact unrecognised type, rather than a control that simply
isn't there and no record of why.

**The build and commit arrangement.** `sleepmix/static/app.js` is committed to
the repository rather than built as part of `pip install sleepmix` — the
package must install with nothing beyond its declared Python dependencies, so
Node and Elm cannot be part of that path. `make ui` (`elm make --optimize`,
from `ui/`) is the target that produces a *shippable* bundle, and it must be
re-run and its output committed by hand whenever anything under `ui/` changes;
nothing automates that step. It is not the only thing that writes `app.js`,
which is the whole reason the guard below has the shape it does: `make ui-dev`
writes an `elm make --debug` build to the same path, deliberately, and
`ui/README.md` warns against committing one.

`ui/hash_sources.py` hashes every `.elm` file under `ui/src`, `ui/elm.json`,
and both port modules (`ui/ports/events.js` and `ui/ports/audio.js`) — and
then the three build outputs, `app.js`, `sleepmix/static/events.js` and
`sleepmix/static/audio.js`. The Makefile writes that hash to
`sleepmix/static/app.js.sha256` next to the bundle;
`tests/test_static_bundle.py` recomputes the same hash with the same script
and fails the suite if it doesn't match what's committed. Hashing the outputs
as well as the inputs is what makes a committed `--debug` build a test failure:
`make ui-dev` changes nothing on the input side and correctly leaves the hash
alone, so an inputs-only digest matched a 333 KB debug bundle exactly as
happily as the 180 KB optimized one. The two served port files are included
for the mirror-image reason — each is a *copy* of its source under
`ui/ports/`, and the copy is what the page actually loads, so editing the copy
used to change nothing any check looked at. A separate test, parametrized over
both pairs, asserts each copy is byte-identical to its source, so the failure
names which file drifted rather than only that something did.

That test is the backstop for a forgotten rebuild, not a substitute for
remembering to do one — it only runs, and only catches the drift, after the
fact. The hash also orders its inputs by sorted path rather than, say, a fixed
manifest order, so it is a drift detector rather than a reproducibility proof:
a module rename that happened to change the sort order while every file's bytes
stayed identical would not change the recorded hash.

`make ui` rebuilds unconditionally rather than being a file target with
prerequisites, because mtime-driven rebuilding was actively wrong here: a
`--debug` bundle written by `make ui-dev` is *newer* than every source, so the
following `make ui` would have skipped the compile and re-recorded the hash of
the debug build as current — turning the guard into a rubber stamp.
