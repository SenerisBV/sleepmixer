# Architecture

This document covers the core render pipeline, the interactive layer built on
top of it (separation → loop → stretch → decay → reverb → sum → sound bed →
master, plus preview, sessions, and progress), and the server that will
eventually expose all of that over HTTP. It does not cover the UI itself —
that's Plan 3; see `docs/project-state.md`.

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
loudest point is always iteration 0 (`progress=0.0`), where `apply_decay` is a
pure passthrough that no decay setting can move. `master_gain` renders exactly
that one window (`render_window(session, 0.0, reverb=True, master=False)`),
measures its peak, and computes the ratio to `db_to_amp(config.output.peak_db)`
— the same target `normalize_peak` aims for on a real render. That single
factor, memoized on the session (`RenderSession.master_gain`), is what
`render_window(..., master=True)` (the default) applies to every subsequent
preview regardless of where in the arc it sits. Applying one factor everywhere
rather than normalizing per window is what preserves the arc: later windows
end up quieter because they genuinely contain less energy, not because each
one was independently pushed back up to full scale, which would flatten the
whole point of the decay.

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

This does not close every gap of the same shape. `master_gain` is measured
from `render_window`, which never mixes the sound bed in at all — but
`run_pipeline` adds the sound bed to the mix *before* peak-normalizing. With
`config.soundbed.enabled = True`, the real render's peak can be higher than
what `master_gain` predicted from stems alone, so a preview would again sit
above the render, for the identical underlying reason: something contributes
to the render's final peak that the calibration window never saw. The sound
bed defaults to off, so this is latent rather than live today; it is recorded,
not fixed, in `docs/project-state.md`.

## Jobs, progress, and sessions

Four design choices in `sleepmix/server/jobs.py`, `sessions.py`, and
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
`separation_reason` (columns this plan adds for a later plan to populate —
nothing sets them yet; see `docs/project-state.md`), and `stems`. `presets`
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
the row just keeps 404ing on peaks (and will keep 404ing on preview and
render once Plan 2b adds them) until the operator re-imports it or fixes the
path by hand.

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
