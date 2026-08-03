# Project state

Status as of the end of the `feat/server-foundation` branch (Plan 2a of the
spec, all 7 tasks complete), on top of `feat/core-hooks` (Plan 1, all 10
tasks complete). Plan 1 gave the pipeline the hooks a local web UI needs —
session staging, cheap preview, structured progress, stable data paths, a
config schema — without building the UI itself. Plan 2a puts an HTTP server
in front of that: a FastAPI app, a SQLite library store, and enough of a
songs API to import a file and draw its waveform. Read `docs/architecture.md`
first for how the pieces fit together; this document is about what's true
right now, what was traded off to get here, and what's explicitly not done
yet.

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
listed first, followed by Plan 2a (`feat/server-foundation`) items found
during this plan's review.

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

- **`MixConfig` has no validation layer.** `config_schema()` publishes bounds
  (`min`/`max`/`step`/`choices`) for every field, but nothing enforces them —
  they are advisory metadata for a UI to build controls from. A config loaded
  from YAML with `tempo.speed: 50` is accepted and rendered. A UI that trusts
  its own controls is fine; an HTTP endpoint accepting arbitrary JSON is not.
  No Plan 2a endpoint accepts a `MixConfig` yet, so this hasn't bitten;
  validation has to land with whichever Plan 2b endpoint first accepts one
  over HTTP (presets, preview, or renders).

- **The Demucs fallback is explained internally now, but that explanation
  doesn't reach a song's record yet.** `separation.separate_detailed` returns
  a `SeparationResult` carrying `fallback_reason`, and `_save_fallback_reason`
  writes that reason into a marker file beside the cached stems, so a later
  cache hit still reports the fallback instead of quietly looking like a
  clean separation — the mechanism the original deferred item was missing
  now exists. But nothing connects it to a song row: `server/store.py`'s
  `songs` table has `separation_status` (`DEFAULT 'pending'`) and
  `separation_reason` columns for exactly this, and no server code ever calls
  `update_song` with them — that requires `POST /api/songs/{id}/separate`,
  which doesn't exist until Plan 2b. Until it does, the UI cannot yet explain
  why a song came back with one `mix` stem instead of four, even though the
  reason is sitting two layers down in the core. That was the whole point of
  the original item, so it's only half-closed.

- **A cached fallback is sticky, and `POST /api/songs/{id}/separate` will have
  to break the stickiness itself.** `separation._cache_key` is
  `sha1(abspath : size : mtime : model)` — it says nothing about whether Demucs
  was actually available when those stems were written. So once a fallback is
  cached, `separate_detailed` finds the cached single `mix` stem, returns early
  at the `_load_cache` hit, and never retries the real model. That includes
  *after* the operator installs the `separation` extra: the file hasn't
  changed, so the key hasn't changed, so they keep getting "Demucs
  unavailable" on a machine where Demucs now works, with no indication that
  the answer is stale rather than current.

  This is invisible today because nothing re-runs separation. Plan 2b's
  `POST /api/songs/{id}/separate` makes it the first thing an operator hits:
  they see one `mix` stem, install the extra, press the button, get the same
  answer. That endpoint needs a force/invalidate path — delete
  `.sleepmix_cache/<key>/` and recompute — or the cache key needs to
  incorporate fallback-ness. Straight `separate()` calls should keep the
  current short-circuit; the point is that the *user-initiated retry* must be
  able to say "no, actually try again."

  Related and same cause: `_save_fallback_reason`'s `reason is None →
  os.remove(path)` branch, which exists to clear a stale marker when a
  later run succeeds, is unreachable in the ordinary flow. Anything that would
  reach it with a stale marker on disk has already returned from the cache hit
  above. It becomes live again as soon as invalidation exists — worth keeping,
  not worth deleting as dead code.

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
  exercises it with eight threads. Plan 2b's job manager will add a genuinely
  separate worker thread writing into `renders`; the lock is already in place
  for it.

- **`load_audio` materialises the whole file in RAM, on every `/peaks`
  request.** `server/api/songs.py`'s `import_song` decodes the file once to
  get `duration_s`/`sample_rate` for the store row, and `get_peaks` decodes it
  again, in full, on *every* call — there is nothing between a request and
  `soundfile.read`. That is repeated cost every time a waveform is drawn, and
  it is worse than slow: a one-hour 96 kHz stereo file is roughly 2.7 GB as
  float32, and `import_song` accepts any path, so a single request can OOM the
  process. `soundfile.blocks()` would make peak computation O(1) in memory and
  is the obvious fix — peaks are a streaming reduction and never need the
  whole array at once. Worth doing in Plan 2b, before the UI starts calling
  `/peaks` on every song-view load.

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

- **Nothing prevents duplicate song rows for the same path.** `add_song`
  always inserts a new row with a new id, so importing the same file twice
  gives two library entries pointing at one file, each with its own render
  history — and the UI has no way to tell the operator they are the same song.
  Either a `UNIQUE` index on `songs.path` (with `import_song` returning the
  existing row instead of 201-ing a duplicate), or a deliberate decision that
  duplicates are allowed and the UI dedupes on display. Pick one in Plan 2b;
  the current state is neither.

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
  `peaks.py` rather than the route so the CLI and Python paths get it too.

- **`test_warm_analysis_makes_the_next_loop_search_fast`'s budget is loose.**
  It asserts a post-warm-up `find_loop` call finishes in under 5 seconds. That
  bound is loose enough that it would also pass if `warm_analysis` silently
  did nothing at all — a genuinely cold `librosa.beat.beat_track` on four
  seconds of audio is slow, but not reliably slower than 5 seconds on modern
  hardware. The test currently only proves warm-up doesn't make things worse,
  not that it does what it claims.
