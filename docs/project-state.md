# Project state

Status as of the end of the `feat/interactive-server` branch (Plan 2b of the
spec, all 8 tasks complete), on top of `feat/server-foundation` (Plan 2a, all
7 tasks complete) and `feat/core-hooks` (Plan 1, all 10 tasks complete). Plan 1
gave the pipeline the hooks a local web UI needs — session staging, cheap
preview, structured progress, stable data paths, a config schema — without
building the UI itself. Plan 2a put an HTTP server in front of that: a FastAPI
app, a SQLite library store, and enough of a songs API to import a file and
draw its waveform. Plan 2b is the rest of the API: preview, background jobs
with live progress and cancellation, renders, and presets. **The server is now
feature-complete for Plan 3** — everything the eventual Elm interface needs to
call already exists and is tested; what's left is building that interface, not
the API underneath it. Read `docs/architecture.md` first for how the pieces
fit together; this document is about what's true right now, what was traded
off to get here, and what's explicitly not done yet.

## Plan 2b: what's built

`sleepmix/server/jobs.py`'s `JobManager` runs separation and renders on a
single background worker thread and fans progress out to per-subscriber
`asyncio.Queue`s; `server/api/jobs.py` exposes polling and cancellation plus an
SSE stream (`GET /api/jobs/{id}/events`) the eventual UI watches. `preview.py`
gained `master_gain` and a `master` parameter on `render_window` so
`POST /api/preview` (`server/api/preview.py`) can return one point in the
decay arc, loudness-matched to the render it represents, as raw WAV bytes in
well under a second. `server/sessions.py`'s `SessionRegistry` keeps up to two
`RenderSession`s warm so consecutive preview requests for the same song stay
cheap. `server/api/renders.py` starts a full render as a background job,
records it in the `renders` table from the moment it's queued, and serves the
finished file or a clean cancellation. `server/api/presets.py` adds named,
validated config snapshots over the `presets` table Plan 2a's schema already
had. `server/api/songs.py` gained `POST /api/songs/{id}/separate`, with a
`force` flag that calls `separation.invalidate_cache` — the fix for a
separation cache that used to keep reporting a stale "Demucs unavailable"
fallback forever, even after the `separation` extra was installed. See
`docs/architecture.md` for how the pieces above actually fit together — the
single worker, the thread-boundary progress hop, the session cap, and why
preview returns bytes rather than a URL are all explained there, not repeated
here.

Task 8, the last of this plan, carried forward four small items from Plan
2a's own final review (an inaccurate loopback-refusal message, a missing
API-level test for the peaks NaN/Inf coercion, an import placed for `flake8`
reasons rather than readability, and an over-claim in this document about an
`unreachable` code branch that turned out to be reachable) and closed three
deferred items from earlier in this plan: a sticky separation-cache fallback,
duplicate library rows for the same imported path, and an unvalidated
negative seed. A fourth earlier item — the Demucs fallback reason not
reaching a song's `separation_status`/`separation_reason` columns — turned out
to have been resolved by `POST /api/songs/{id}/separate` too, in passing,
before Task 8 started. Each of those is removed from the list below rather
than left listed, since leaving a resolved item as a known weakness is
exactly the kind of inaccuracy this document exists to avoid.

## Plan 2a: what's built, and what it deliberately doesn't do yet

`sleepmix/server/app.py`'s `create_app` factory, `server/store.py`'s SQLite
store (songs/presets/renders tables), `server/warmup.py`'s startup JIT
warm-up, and `server/api/schema.py` + `server/api/songs.py` (import a song by
path, list/fetch songs, compute waveform peaks) are all there and tested.
`sleepmix ui` starts it, serving on `127.0.0.1:8765` by default and opening a
browser tab. It refuses a non-loopback `--host` unless `--allow-remote` is
passed, because the server has no authentication and `import_song` will read
any audio file the process can read — see the deferred-items section below for
the full shape of that constraint.

That's the whole surface. Plan 2a does **not** yet have: a preview endpoint
(`POST /api/preview` and the `audio.encode_wav` it needs), renders (starting,
cancelling, downloading, or a job manager to run them in the background), an
SSE progress stream, presets CRUD over the table Task 2 already created, or a
`RenderSession` registry keyed by song. All of that — the interactive
machinery — is Plan 2b. Until it lands, this server can register a song and
draw its waveform and nothing else; it cannot render or preview anything.

`sleepmix/static/index.html` is a deliberate placeholder, not a preview of
the finished UI. `app.py` serves it at `/` today only so there is something
to load in a browser and confirm the server is up; Plan 3 replaces it
outright with a compiled Elm application. Don't read anything about the
eventual interface into its current contents.

## Plan 1 (`feat/core-hooks`) recap

What it built: everything under "What each module owns" in
`docs/architecture.md` up to and including the server section —
`paths.py`, `progress.py`, `session.py`, `preview.py`, the config schema in
`config.py`, and the pre-existing render pipeline (`pipeline.py`,
`analysis.py`, `separation.py`, `timestretch.py`, `disintegration.py`,
`effects.py`, `soundbed.py`, `looping.py`) unchanged in behavior except where
noted below. Nothing in that branch served HTTP; `cli.py` still only did
`render` and `init-config`. It built the load-bearing capabilities a server
and a UI would need without exposing any of them to a user who wasn't calling
Python directly.

What still sits beyond both plans so far: the Elm application itself
(library view, song view, mixer, render screen, schema-driven controls
consuming `config_schema()`, Web Audio buffer swapping at loop boundaries
using `render_window`) is Plan 3. Segment selection and arrangement, output
length as an arrangement property, and a bundled desktop app are noted in the
spec as future work beyond any plan written so far.

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

**Render output changed a second time, later in this same branch.**
`disintegration.plan_iterations` was returning two more iterations than
`build_disintegrating_stream` actually executes, so the decay arc stopped
short — a 20-minute render off a 9-second loop reached progress 0.9932 and
never got to the configured `*_end` values at all, and
`preview.preview_iteration_index(session, 1.0)` pointed at an iteration no
render produces. Dropping the stray `+ 1` fixed both, and in doing so shifted
every render's iteration count by one and therefore its whole decay curve
slightly. This is a *second*, separate break in output compatibility, and it
means renders are not comparable across this branch's own history either —
output from an early commit on `feat/core-hooks` will not match output from
its tip. Byte-reproducibility was already deliberately forfeited above, so
this was accepted rather than worked around; but if you are diffing renders to
investigate something else, check which commit produced them first.

**A preview window is bit-identical to the corresponding render iteration
pre-reverb, but only representative of it with reverb on.** `render_window`
applies each stem's decay and reverb (with that stem's `reverb_send`) in the
same order `pipeline._process_stem` does, so a dry preview and the dry render
at the same iteration produce identical samples. With reverb enabled they
diverge slightly, because a preview window is rendered in isolation and has
no reverb tail bleeding in from the *previous* iteration — a real render's
reverb is a continuous process across the whole stream, a preview's is not.
This was found and partially fixed during Task 9's review (see the addendum at
the end of `docs/superpowers/plans/2026-08-03-core-hooks.md`).

The tail-bleed gap has since been closed as far as it usefully can be.
`preview._reverbed_window` renders the *preceding* iteration as leading
context, reverbs it together with the window, and cuts the window back out at
an offset measured from the installed backend
(`effects.reverb_dry_offset`). So a wet window is now exactly as long as the
loop and opens with the previous iteration's reverb tail rather than the
pre-delay's silence — both of which matter because the UI plays this buffer on
a loop, where a longer-than-the-loop buffer that starts with 40ms of nothing
gaps and clicks every cycle. What remains is one approximation: the context is
concatenated, where a real render crossfades consecutive iterations over
`cycle_crossfade_ms`, so the reverb hears a join the render does not. A wet
window is therefore still representative rather than bit-identical; a dry one
remains exact.

**The separation cache moved.** It used to live at `.sleepmix_cache/`
relative to the working directory; it now lives under
`paths.cache_dir()` (a per-user app-data directory, see
`docs/architecture.md`). This repository still has a `.sleepmix_cache/` at
its root — roughly 170MB across two cached songs (`004542e5a96e70ee` and
`68b53b05350142ff`) — left over from before this branch. It is orphaned:
nothing on this branch reads it, so those songs will be re-separated (a real
Demucs call, ~10s+ depending on hardware) the next time each is rendered. It
can be deleted; nothing here depends on it existing.

## Known weaknesses, deferred deliberately

These were identified and left as-is; each has a reason it wasn't worth
fixing in the branch that found it. Plan 1 (`feat/core-hooks`) items are
listed first, followed by Plan 2a (`feat/server-foundation`) items, followed
by Plan 2b (`feat/interactive-server`) items found during this plan's review.

- **A preview does not account for the sound bed, and it is the most
  important gap left in the level-matching this plan otherwise fixed.**
  `preview.master_gain` measures its one calibration window with
  `preview.render_window(session, 0.0, reverb=True, master=False)`, which sums
  only the configured stems — it never calls `soundbed.build_soundbed`. But
  `pipeline.run_pipeline` adds the sound bed to the mix *before*
  `normalize_peak` runs, so when `config.soundbed.enabled` is `True` the real
  render's peak includes noise and binaural tones a preview's calibration
  never saw. The real peak can then be higher than `master_gain` predicted, so
  a preview would once again sit above the render it represents — the exact
  defect `docs/architecture.md`'s "Matching a preview's loudness to the
  render" describes fixing, reappearing for a different reason.
  `SoundbedConfig.enabled` defaults to `False`, so this is latent rather than
  live in the default configuration, but it is not fixed: enabling the sound
  bed and previewing is enough to trigger it today.

- **`server/jobs.py`'s `_jobs` and `_subscribers` dictionaries are never
  evicted.** Every job ever submitted — every separation, every render —
  stays in `JobManager._jobs` for the life of the process, and every job id
  gets a permanent (if eventually empty) entry in `_subscribers`. Fine for a
  session-length local tool that gets restarted often; it becomes a slow
  memory leak for a server left running for days.

- **A `BaseException` escaping a job leaves it stuck at `"running"` forever.**
  `JobManager._run` catches `Cancelled` and `Exception`, but a `SystemExit` or
  `KeyboardInterrupt` raised inside a job function would propagate past both,
  and nothing in `_run` would ever set a terminal status — the job's row (and
  any render or song row it was updating) is left reporting `"running"`
  indefinitely, and the SSE stream watching it never closes.

- **`server/jobs.py` imports `field` from `dataclasses` and never uses it.**
  `Job`'s fields all take plain defaults; none needs `field(default_factory=…)`.

- **No test exercises SSE client-disconnect cleanup, and the heartbeat branch
  is untested.** `server/api/jobs.py`'s `stream_job` unsubscribes in a
  `finally` block whose correctness rests entirely on Starlette propagating
  cancellation into the generator when a client goes away mid-stream — nothing
  in `tests/test_api_jobs_sse.py` drops a connection before a job finishes to
  prove that actually happens. The `asyncio.TimeoutError` → `": keepalive\n\n"`
  branch, reached when `_HEARTBEAT_SECONDS` (15s) elapses with no event, is
  likewise never driven by any test.

- **`separation.invalidate_cache` imports `shutil` inside the function,** while
  the module imports `os` and `hashlib` at the top. Harmless, just inconsistent
  with the rest of the file.

- **`encode_wav` has no test with a mono buffer.** `tests/test_audio_encode.py`
  only ever builds stereo (and empty-stereo) buffers; a single-channel
  `AudioBuffer` going through `encode_wav` is untested.

- **`presets.py` validates a config only through a call whose result it
  discards.** `create_preset` calls `MixConfig.from_dict(body.config)` purely
  so a bad config raises `ValueError` (turned into a 400) before anything is
  stored — the returned `MixConfig` is never used; the raw dict is what gets
  saved. That makes the validation a side effect of a call that looks like
  dead code, one `# unused` cleanup away from being deleted along with the 400
  path it provides. Separately: `start_render` *does* independently reconstruct
  and validate a `MixConfig` from whatever config it's given, preset or not, so
  a preset is never actually used unvalidated — but nothing prevents an
  invalid preset from being *saved* in the first place except that same
  discardable call, so if it were ever removed, a bad preset would fail
  silently at save time and loudly, later, the first time someone tries to
  render with it.

- **`RenderSession`'s loop-stage cache key is coarser than it needs to be.**
  It covers all of `LoopConfig`, so changing only `crossfade_ms` — which only
  feeds `make_seamless`, not `find_loop` — invalidates the loop point and
  pays a ~1s `find_loop` recompute anyway. The fix is to split the cache key
  so `crossfade_ms` invalidates only `prepared_loop`'s cache, not
  `loop_point()`'s. Not done because no caller yet changes `crossfade_ms`
  interactively without also touching something that already invalidates
  the loop.

- **`test_reporter_receives_ordered_monotonic_events` cannot fail.**
  `ProgressReporter.emit` clamps its own output to be monotonic
  (`docs/architecture.md`), so this test is asserting a property the code
  under test enforces on itself — a regression in `pipeline.py`'s per-stem
  `stage_range` arithmetic that produced out-of-order *inputs* to `emit`
  would be silently absorbed by the clamp and this test would still pass.

- **`analysis._estimate_tempo` and `_librosa_loop` each have their own
  `librosa.beat.beat_track` call site.** The two paths are mutually exclusive
  within a single `find_loop` call — an explicit `start_s`/`end_s` short-
  circuits auto-detection entirely, so `beat_track` is never invoked twice in
  one call — but the duplicate call sites could still share a helper.

- **`MixConfig.seed` and `separation_model` carry no field metadata.** Every
  other config field has a `label`/`help`/bounds dict for `config_schema()`
  to read; these two fall through to auto-generated labels
  (`"Seed"`, `"Separation model"`) and no help text, because they sit
  directly on `MixConfig` rather than in one of the nested per-section
  dataclasses `config_schema()` was designed around.

- **`MixConfig`'s validation layer covers one field.** `MixConfig.validate()`
  (called from `MixConfig.from_dict`, which every config-accepting endpoint —
  presets, preview, renders — routes through) rejects a negative `seed`, and
  that is the only thing it checks. `config_schema()` publishes bounds
  (`min`/`max`/`step`/`choices`) for every other field, but nothing enforces
  them — they remain advisory metadata for a UI to build controls from. A
  config posted with `tempo.speed: 50` is still accepted and rendered.

- **`_save_fallback_reason`'s `reason is None → os.remove(path)` branch is
  reachable — an earlier version of this document said otherwise.** The
  original claim was that anything reaching this branch with a stale marker
  on disk would already have returned from `_load_cache`'s cache hit first.
  That reasoning missed the case its own docstring names: if the marker is
  written but `_save_cache` then fails or is interrupted before any `.wav`
  file lands, the next call finds a marker with no cached stems.
  `_load_cache` requires at least one `.wav` file to report a hit, so it
  returns `None` — the call recomputes rather than trusting the directory
  (`tests/test_separation.py::test_a_marker_without_stems_does_not_masquerade_as_success`
  proves the recompute happens; it just doesn't happen to succeed in that
  test). If a recompute in that state *does* succeed, `_save_fallback_reason`
  is called with `reason=None` and finds the earlier run's marker still on
  disk, and removes it. `separation.invalidate_cache` (added this plan) does
  not add a second route to this same line — it deletes the whole cache
  directory, marker included, so a forced re-separation never finds a marker
  left over to remove; it sidesteps the branch rather than exercising it. The
  original conclusion — keep the branch — was right regardless.

- **`Store` is locked now — and the reason the earlier deferral was wrong is
  worth keeping.** An earlier version of this document claimed "every request
  in this plan runs on FastAPI's single event loop." **That was false.** Every
  route in `server/api/` is declared `def`, not `async def`, and FastAPI runs
  sync path-operation functions in an AnyIO threadpool — instrumenting
  `Store.list_songs` and issuing `GET /api/songs` records the call on an
  `AnyIO worker thread`, not `MainThread`. So the store was already reachable
  from several threads at once, and would have been from the Elm UI's very
  first paint, which fires several requests in parallel by design.

  `sqlite3.threadsafety` is 3 (SERIALIZED) on the development machine, so
  nothing corrupted — but that is platform-dependent, and
  `check_same_thread=False` disables the only guard Python offers. Two
  problems were real regardless of the platform: `commit()` is
  connection-wide, so one thread's commit flushes another's in-flight implicit
  transaction; and `update_song`/`update_render` are read-modify-write
  (`get` → `UPDATE` → `get`) and lose updates under concurrency.

  Every public method on `Store` now holds a `threading.RLock` for its whole
  body. **`RLock`, not `Lock`** — `update_song` calls `get_song` while already
  holding the lock, and a non-reentrant lock deadlocks there on the first
  update (verified). `tests/test_store.py::test_concurrent_writers_and_readers_do_not_lose_rows`
  exercises it with eight threads. Plan 2b's `JobManager` (`server/jobs.py`)
  did go on to add a genuinely separate worker thread writing into `renders`
  and `songs`; the lock was already in place for it, and nothing about that
  addition needed to touch `Store`.

- **`load_audio` still materialises the whole file in RAM, on every `/peaks`
  request.** `server/api/songs.py`'s `import_song` decodes the file once to
  get `duration_s`/`sample_rate` for the store row, and `get_peaks` decodes it
  again, in full, on *every* call — there is nothing between a request and
  `soundfile.read`. That is repeated cost every time a waveform is drawn, and
  it is worse than slow: a one-hour 96 kHz stereo file is roughly 2.7 GB as
  float32, and `import_song` accepts any path, so a single request can OOM the
  process. `soundfile.blocks()` would make peak computation O(1) in memory and
  is the obvious fix — peaks are a streaming reduction and never need the
  whole array at once. Not done in Plan 2b either; still worth doing before
  the eventual UI starts calling `/peaks` on every song-view load.

- **`import_song` accepts an arbitrary absolute filesystem path from the
  request body with no allow-listing.** It resolves `~` and relative
  components and 400s cleanly if the result isn't a readable file — it
  doesn't crash — but nothing restricts *which* files under the operating
  system's permissions it will read, and `/peaks?buckets=20000` will hand back
  a detailed summary of whatever it read. That's acceptable for what this is:
  a loopback-only tool reading the operator's own music on their own machine.
  It stops being acceptable the moment the server is bound anywhere else.

  That constraint is no longer implicit. `cli.py`'s `ui` command refuses a
  non-loopback `--host` unless `--allow-remote` is passed, and says why in the
  refusal; the README's UI section says the same thing in prose. **A path
  allow-list is still the thing that would actually make a non-loopback bind
  safe, and it does not exist** — `--allow-remote` is an informed-consent
  switch, not a mitigation.

- **DNS rebinding is not mitigated, deliberately.** Binding loopback stops
  other machines from connecting; it does not stop a web page the operator
  visits from rebinding its own hostname to `127.0.0.1`, at which point the
  page is same-origin with the API and can drive it — import a path, read the
  waveform back. `TrustedHostMiddleware` with a `Host` allow-list is the cheap
  mitigation, but it needs care rather than a one-liner: FastAPI's
  `TestClient` sends `Host: testserver`, so a naive allow-list of
  `127.0.0.1`/`localhost` fails every request in the suite at once. Deferred
  for that reason, not overlooked. Whoever adds it must allow the test host
  (or make the allow-list injectable) in the same change.

- **`cli.py`'s `ui` command only guards the `uvicorn` import.** The
  `try/except ImportError` around `import uvicorn` does not extend to the
  following `from .server.app import create_app`, which pulls in `fastapi`.
  An install with `uvicorn` present but `fastapi` missing (an unusual but
  possible partial install) shows a raw `ImportError` traceback instead of
  the `pip install "sleepmix[ui]"` hint the guard exists to give.

- **Waveform peaks are computed on the mono downmix.** `peaks.compute_peaks`
  calls `buf.to_mono()` before bucketing min/max pairs, so a transient present
  in only one channel — a hard-panned hit, for instance — is averaged down
  with the other channel rather than shown at full height. The drawn waveform
  is a legitimate summary of loudness but not a faithful per-channel picture.

  It does now clamp non-finite samples (`np.nan_to_num`, immediately after the
  downmix). A float-subtype WAV can legally carry `NaN`/`±Inf`; those survived
  `float()` and pydantic serialized them to JSON `null` on a `-> dict` route,
  which would fail the Elm frontend's `list (list float)` decode and blank the
  whole waveform with nothing logged server-side to explain it. The clamp is in
  `peaks.py` rather than the route so the CLI and Python paths get it too. The
  clamp itself was tested only at the function level until this plan;
  `tests/test_api_songs.py::test_peaks_are_finite_for_a_file_containing_nan`
  now drives a `NaN`/`Inf`-carrying WAV through `GET /api/songs/{id}/peaks`
  end to end.

- **`test_warm_analysis_makes_the_next_loop_search_fast`'s budget is loose.**
  It asserts a post-warm-up `find_loop` call finishes in under 5 seconds. That
  bound is loose enough that it would also pass if `warm_analysis` silently
  did nothing at all — a genuinely cold `librosa.beat.beat_track` on four
  seconds of audio is slow, but not reliably slower than 5 seconds on modern
  hardware. The test currently only proves warm-up doesn't make things worse,
  not that it does what it claims.
