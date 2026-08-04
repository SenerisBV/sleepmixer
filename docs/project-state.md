# Project state

Status as of the end of the `feat/mixer` branch (Plan 3b of the spec, all 7
tasks complete), on top of `feat/elm-shell` (Plan 3a of the spec, all
6 tasks complete), on top of `feat/interactive-server` (Plan 2b, all 8 tasks
complete), `feat/server-foundation` (Plan 2a, all 7 tasks complete), and
`feat/core-hooks` (Plan 1, all 10 tasks complete). Plan 1 gave the pipeline the
hooks a local web UI needs — session staging, cheap preview, structured
progress, stable data paths, a config schema — without building the UI itself.
Plan 2a put an HTTP server in front of that: a FastAPI app, a SQLite library
store, and enough of a songs API to import a file and draw its waveform.
Plan 2b built the rest of the API: preview, background jobs with live progress
and cancellation, renders, and presets. Plan 3a is the first real frontend —
an Elm application replacing the placeholder `index.html` — and it is scoped
to *browsing and separating*, not yet to mixing or rendering. Plan 3b adds the
mixer: controls generated from the config schema, a scrubber over the decay
arc, and audio that plays while you shape it. Rendering still has no screen.
Read
`docs/architecture.md` first for how the pieces fit together; this document is
about what's true right now, what was traded off to get here, and what's
explicitly not done yet.

## Plan 3b: the mixer

`ui/src/Page/Mixer.elm` is the screen the previous two plans were building
toward — a progress scrubber over the decay arc, per-stem enable/gain/reverb-
send/decay, solo, and the loop region drawn on the waveform with its tempo. It
is reached from the song screen and it plays: `ui/ports/audio.js` fetches
`POST /api/preview`, decodes the WAV and loops it, swapping buffers at the next
loop boundary.

Almost none of the controls are written. `GET /api/schema` describes every
config field and `ui/src/Config.elm` holds the values and re-nests them for
`MixConfig.from_dict`; neither module names a single config parameter, with
three structural exceptions it documents. Adding a field in
`sleepmix/config.py` puts a control in the mixer with no frontend change. The
same reasoning went the other way once during this task: `MixConfig.seed` now
carries `min: 0` in its metadata, because `validate` rejects a negative seed and
the UI's bounds come from the schema alone — without the floor, a generated
control could produce a config the server refuses, and it would surface as a
400 on a preview rather than as a slider that will not go there.

What it does not do yet, and what to know before changing it:

- **The mixer starts from the schema's stem defaults, not `MixConfig`'s curated
  ones — and that is a difference on every stem, not just drums.** A fresh
  mixer gives all four stems one identical setting (`StemConfig` +
  `StemDecayConfig` defaults). `MixConfig`'s list is four different ones, and
  they differ as follows: `drums` enabled here / disabled there; `bass` decay
  enabled here / disabled there; `vocals` `linear` here against `exp` there
  plus lowpass 1600 → 2200 Hz, amplitude -9 → -16 dB and spectral holes
  0.3 → 0.45; `other` lowpass 1600 → 2400 Hz and amplitude -9 → -4 dB. The
  CLI's per-stem shaping is simply absent until someone moves a slider, so a
  mix built in the UI and a mix built by `sleepmix render` from defaults are
  audibly different things. The schema deliberately does not describe
  list-typed fields, so there is nothing to read the curated list from, and
  hard-coding it in Elm is exactly the drift the schema exists to prevent. A
  `GET /api/config/default` is the right fix and is parked for a later plan.
- **The sound bed is not in previews.** `preview.render_window` does not add it;
  `pipeline.run_pipeline` does. The section says so in place, because otherwise
  you turn on binaural beats, hear nothing, and conclude the mixer is broken.
- **The mixer will not open without stems, or while a separation is running.**
  Its rows *are* the stems, and a preview of an unseparated song would run
  Demucs inside the preview lock with nothing reporting progress. A separation
  finishing also discards the warm session and can change the stem list under
  an open mixer, which is the other half of the gate.
- **"Preparing…" is indeterminate on purpose.** The first preview is the
  117-second path and nothing in it reports progress, so the bar animates and
  claims nothing. Do not replace it with a fraction; there is no fraction. If
  that preview *fails*, `Preview.failed` puts the session back to `Cold` rather
  than to `Idle`: nothing came back, so nothing is known to be playable, and
  opening the controls over silence would break the one promise this screen
  makes. The panel says so and offers to try again.
- **`separation_model` has no control in the mixer, deliberately.** It is the
  one config field whose change is not a cheap re-render: `update_config` nulls
  the session's stems, so the next preview runs Demucs inside the per-song
  preview lock — minutes, no progress, and the screen already playable. The
  value still travels with every preview; only the control is absent. It
  belongs beside the Separate button, which already has a job and a progress
  bar, and that is a later plan.
- **Nothing automated asserts that a port command is emitted.** Elm `Cmd`s
  have no equality, so an implementation where `sendPreview` returned
  `Cmd.none`, or `leaveMixer` omitted `stopPreview ()`, would pass all 160 Elm
  tests — every assertion in `MixerTest.elm` and `PreviewTest.elm` is on the
  model half of `update` (what state `Preview.request`/`Preview.arrived`
  produce), never on whether a real `Cmd` actually left the program and
  reached `audio.js`. Compensated by manual `curl` against a running server
  during this task's own review, not fixed — the gap is structural (Elm
  offers no way to inspect a `Cmd` from a test) rather than a missing
  assertion someone forgot to write, so closing it would need a different
  testing approach, not more tests of this shape.
- **Soloing a stem the config has disabled returns a 200 and a 1-frame WAV,
  not an error — and this is reachable from the shipped mixer, not only from
  `curl`.** Found during this task's manual verification: with `MixConfig`'s
  own defaults (`drums` disabled), `POST /api/preview` with
  `stems: ["drums"]` came back `200 OK` with a 48-byte file — a valid WAV
  header wrapped around a single silent frame. The path there is
  `plan_stem_configs` (`config.py`), which drops any configured-but-disabled
  stem before `render_window`'s own `stems` filter ever sees it, so asking for
  only a disabled stem leaves `render_window`'s `planned` list empty; nothing
  in that function distinguishes "you asked for a stem that doesn't exist"
  from "you asked for a stem that exists but is switched off," and both fall
  through to the same `silence(1, channels, sr)` — a buffer of exactly one
  frame, not one loop's worth of quiet. A browser handed this plays nothing
  and gets no error to show, which is the same failure shape the mixer's own
  strict decoders exist to avoid everywhere else: wrong-and-quiet rather than
  loud.

  `Page/Mixer.elm`'s Solo button is disabled while a stem's own `enabled`
  checkbox is off (`stemRow`'s comment names this exact hazard: "soloing a
  stem the config has switched off would ask the server for a mix of
  nothing"), which stops the button from *starting* a solo on a disabled
  stem. It does not stop the other order: solo a stem first, while it is
  enabled, then uncheck that same stem's `Enabled` box while it is still the
  soloed one. `toggleField` never inspects or clears `state.solo`, and
  `withMixer` fires a fresh preview after *every* mixer state change,
  building its `stems` list from `soloedStems` alone — so unchecking
  "Enabled" on the currently-soloed stem sends exactly the request above and
  gets back the same 48-byte file, with the Solo button now shown disabled
  and nothing on screen explaining why the audio went silent. Real, reachable
  through ordinary use of the mixer as shipped, and worth the final review's
  attention rather than being fixed here.
- **The loop region is re-fetched only when `loop.start_s` or `loop.end_s`
  changes**, because those are the only two things `GET /api/songs/{id}/loop`
  takes. `bars`, `beats_per_bar` and the search window are config fields a
  render honours and that endpoint cannot express, so the drawn region can
  differ from what a render detects once those are changed. The endpoint also
  still decodes the whole file and runs beat tracking on every call with no
  caching (recorded during Plan 3b Task 2), and the mixer now calls it on
  entering a song and on those two edits.
- **Collapsed sections use `<details>`, so their open/closed state lives in the
  DOM rather than in the model.** Nothing depends on it and Elm never sets
  `open`, so the browser keeps whatever the user did; a screenshot of the model
  will not tell you what is expanded.
- **Field order within a section is alphabetical**, because `Schema.elm` decodes
  into a `Dict` and JSON object order does not survive that. It reads oddly in
  places (`lowpass_end_hz` above `lowpass_start_hz`). Preserving the server's
  order would mean decoding to key-value pairs and threading order through.
- **`previewReady` carries a JSON value, not `()`.** `audio.js` sends
  `{ durationS }`, and a `()` port compiles to `Json.Decode.null`, which rejects
  an object at runtime with a port error Elm cannot catch — the screen would sit
  at "Preparing…" forever with audio playing underneath. The payload is decoded
  leniently and shown as the length of the loop now playing.
- Presets and the render screen are still not built; that is Plan 3c, and it
  is specifically **the render screen (start, watch, cancel, download), the
  presets UI, queue visibility, and a warning before importing a file large
  enough to block everything behind it** — the four things this plan's own
  closing section names as out of scope, carried over unchanged because
  nothing in this task changed any of them.
- The parked defect from Plan 3a is untouched: reloading mid-separation shows an
  enabled button reading "Separating…", because the disable comes from client
  state and the label from the server's status. The mixer's own gate reads the
  server status as well as the flag, so it does not inherit the bug.

## Plan 3a: what's built, and what it deliberately doesn't do yet

`ui/src/Main.elm` is a compiled Elm application (`sleepmix/static/app.js`)
served at `/` in place of the old placeholder page. It talks to the Plan
2a/2b API exclusively over HTTP and one pair of ports
(`ui/ports/events.js` for job progress via SSE) — nothing about the API
changed to accommodate it, exactly as Plan 2b's own document predicted. What
it does: shows the library (`Page.Library`), imports a song by filesystem
path, opens a song (`Page.Song`) and shows its waveform as SVG
(`Waveform.elm`, peaks fetched from `GET /api/songs/{id}/peaks`), starts stem
separation and tracks its progress live over `GET /api/jobs/{id}/events`, and
shows a separation failure or fallback reason in place rather than swallowing
it. Decoders (`ui/src/Api.elm`) are strict: an unrecognised `separation_status`
or job `status` fails the decode rather than being coerced into a default
case. See `ui/README.md` for how to build, develop, and test this, and
`docs/architecture.md`'s new frontend section for the design reasoning behind
each of those choices.

**What it deliberately does not do yet — all of it Plan 3b.** Kept as written
rather than edited into the past tense, because the reasoning is the record of
why the next plan was shaped the way it was. Plan 3b has since closed: audio
playback, orphaned `running` rows, the loop region and its endpoint, the mixer,
preview playback, and schema-driven controls. Still open from this list: the
import-size warning, the two-point separation progress bar, the render screen,
and presets.

- **Nothing in the interface plays audio, and nothing says so.** This is the
  gap that actually bit during testing. `Page.Song` announces "separated" with
  four stem names and then offers no next action — no preview, no render, no
  player. Grep `ui/src` for anything audio-related and you get three code
  comments. The API can do all of it (`POST /api/preview` returns WAV bytes in
  well under a second once a session is warm; `POST /api/renders` produces a
  file), but no view calls those endpoints. A reasonable person separates a
  song, finds no way to hear anything, and concludes the tool is broken. Until
  Plan 3b lands, the song view should say plainly that preview and render
  arrive later — announcing success while offering nothing is worse than
  announcing nothing.

- **Orphaned `running` rows survive a server restart.** `separation_status` is
  set to `running` before the job starts, and only a terminal status or one of
  `separate_song`'s two exception handlers clears it. Process death bypasses
  both, so killing or suspending the server mid-separation leaves the song
  claiming to separate forever, with no job behind it — the in-memory
  `JobManager` died with the process. Observed in practice: two rows stranded
  at `running` after a `Ctrl-Z`, which suspends rather than kills and looks
  identical to having exited. The fix is small and belongs at startup: the job
  manager is in-memory, so **any `running` row at boot is definitionally
  orphaned** and should be reset to `pending`. Plan 2b fixed this class of bug
  for exceptions; process death is the case that was missed.

- **No warning about how long a large import will take.** A 70-minute file
  imports instantly and then queues a separation that takes a very long time
  and holds several gigabytes — measured at 6.2 GB resident for one such job.
  Jobs run one at a time by design, so a single large file blocks every
  smaller one behind it, and the interface shows neither an estimate nor the
  queue depth. `GET /api/jobs` lists them, but no view renders it.

- **No loop region on the waveform, and no route that could draw one.** The
  spec's Song view asks for the detected loop region marked plus a tempo
  readout, and Plan 3a's goal line promised "see its waveform and detected
  loop" — but nothing in that plan could have delivered it, because **no
  endpoint exposes a detected loop or a tempo.** `server/api/songs.py` has
  import, list, get, peaks and separate, and nothing else; `analysis.find_loop`
  and `_estimate_tempo` are reachable only from inside a render or a
  `RenderSession`, never over HTTP. `Waveform.loopRegion` was written anyway
  and is dead code on this branch: `Page/Song.elm` passes `loop = Nothing` and
  has nothing else it could pass. The plan's goal line has since been corrected
  (see the note at the top of
  `docs/superpowers/plans/2026-08-04-elm-shell.md`), and the shipped docs never
  claimed the loop, so nothing else needs unsaying. **This is a stated
  dependency for the next plan, not an implementation detail:** drawing the
  loop region needs a new server route — something like
  `GET /api/songs/{id}/loop` returning start/end seconds and a tempo — and that
  route is where the cost lives, since a cold `find_loop` is the ~1 s librosa
  call the session cache exists to avoid paying twice. Do not plan the Elm half
  as though the data is already there.

- **The separation progress bar is real but has nothing to animate.** The SSE
  machinery works end to end — `watchJob` opens the stream, events decode,
  `Watching`'s fraction reaches the bar — but the separation job emits only two
  progress points: `0.0` when it starts and `1.0` when it completes, which is
  terminal and clears the bar. So the bar renders, sits at 0% for the entire
  run, and then vanishes; the percentage beside it reads "0%" the whole time.
  The port machinery is right and the payload is thin. **Plan 3b's render
  progress should not assume the bar moves** — a render reports many
  intermediate fractions (`pipeline.run_pipeline`'s stage checkpoints, see
  `docs/architecture.md`) and will animate properly, but anything inheriting
  this bar for separation should either accept the two-point behaviour or make
  `separation.separate` report per-stem progress first.

- **No mixer.** Nothing in this UI reads `/api/schema` or lets a user touch a
  single decay/reverb/tempo parameter. Separation is the only action a song
  screen offers.
- **No preview playback.** `POST /api/preview` exists and is tested on the
  server side, but nothing in this frontend calls it, and there is no
  `ports/audio.js` yet — no `decodeAudioData`, no looped playback, no buffer
  swap at a loop boundary.
- **No render screen.** Starting, watching, cancelling, or downloading a full
  render (`server/api/renders.py`, all built in Plan 2b) has no frontend at
  all.
- **No schema-driven controls.** `config.config_schema()` — bounds, labels,
  and help text for every `MixConfig` field — is not consumed anywhere in
  `ui/`.
- **No presets.** `server/api/presets.py`'s CRUD has no corresponding screen.

**What the final whole-branch review changed.** Six things, all of which had
shipped looking finished. (1) `sleepmix/static/index.html`'s stylesheet was
written for a health-check-only page and defined three of the fifteen classes
the Elm views emit — so `div.progress-fill`, an empty div carrying only an
inline `width: N%`, had no height, no background and no colour, and **the live
progress bar this whole branch exists to deliver rendered as nothing at all.**
Library rows were default bulleted `<li>`s with a click handler and no
`cursor: pointer`. The stylesheet now covers every emitted class, and
`progressBar` gained a `.progress-track` element so the fill has something of a
known size to be a percentage of. (2) The separation state became one union —
see `ui/README.md` for the shape and the three reachable paths that used to
strand the panel at "Separating…" forever. (3) Responses are tagged with a
monotonic request id rather than a song id. (4) `ui/hash_sources.py` hashes the
build *outputs* as well as its inputs, which is what makes a committed
`make ui-dev` bundle a test failure; `sleepmix/static/events.js` is separately
asserted byte-identical to `ui/ports/events.js`. (5) The plan's goal line was
corrected — see the loop-region entry above. (6) `.github/workflows/tests.yml`
is the first CI this repository has had.

**A residual race in the stream-failure port, stated because it is a design
choice and not an oversight.** `ports/events.js` reports every `EventSource`
`onerror` to Elm, and Elm decides whether it mattered by checking whether it is
still `Watching` that job. That works because Elm processes an incoming port
send synchronously — the terminal event's `update` runs, sets `Idle` and
dispatches `stopWatchingJob` before `onmessage` returns — and because `events.js`
stays silent about a connection Elm has already told it to drop. If a browser
ever delivered `onerror` for the server's normal end-of-stream *before* the
preceding terminal event's `update` completed, the UI would show a spurious
"the progress stream closed before it reported finishing". The consequence is a
misleading message on an already-finished separation, not a stuck panel; the
alternative — teaching `events.js` to recognise a terminal payload — would put
the decision in the layer that is deliberately dumb.

**The CI workflow does not use `pipenv`, deliberately.** The `Pipfile` installs
`sleepmix[all]`, which pulls demucs and torch — gigabytes, to run a suite that
passes without them through the graceful-degradation path every optional
dependency already has (the local run reports `Demucs separation unavailable
(no torch)` and passes). `.github/workflows/tests.yml` does
`pip install -e ".[dev]"` and `pytest -q` instead. It does not install Elm
either: the staleness guard is `ui/hash_sources.py`, which only reads files, so
a forgotten `make ui` is caught without a toolchain.

**A constraint carried forward from Plan 2b that shapes all of the above.**
Plan 2b's own document (below, under "Jobs, progress, and sessions") measured
that `POST /api/preview` serializes per song — including the cold path, where
building a `RenderSession` from scratch (separation + loop detection +
time-stretch) was measured at **117 s cold versus 73 ms warm**. Every request
against a cold song's session queues behind whichever request got there
first, and each queued request occupies one of FastAPI's AnyIO threadpool
threads for the whole wait, not just its own render time. A scrubber that
fires one `/api/preview` request per drag event — the naive implementation —
would, against a cold song, queue dozens of requests behind that single 117 s
render, each pinning a thread for the duration. **Plan 3b must coalesce or
cancel superseded preview requests rather than firing one per drag event, and
should not enable the scrubber at all until the song's session is warm** (the
per-song equivalent of `/api/health`'s `is_warm()`, which currently only
covers the process-wide librosa JIT warm-up, not per-song session state).
This is a requirement on 3b's design, not an optimisation to consider later.

**Two process lessons from this plan, carried forward because Plan 3b is
where they'll bite hardest.** First: an implementer on this plan, satisfying
a "see it in a browser" verification step, drove GUI automation against the
operator's own desktop — real Safari tabs, an unrelated Terminal window, a
Finder window with sensitive files open — and tripped a macOS TCC permission
dialog the operator had to notice and dismiss by hand. Verification on this
codebase goes through the API with `curl`, never a browser driver, an
AppleScript `do JavaScript` call, a screenshot tool, or a browser-automation
MCP. Plan 3b adds actual audio playback, which is a far more tempting thing
to want to "just see (hear) working" than a waveform was — the instruction
not to automate a browser matters more there, not less. Second: a server
started for manual verification writes to the operator's real library
(`~/Library/Application Support/sleepmix/library.db` on macOS) unless told
otherwise — this happened once during this plan and was caught and cleaned
up, but the instruction should not have allowed it to happen at all. Always
verify against `SLEEPMIX_DATA_DIR=$(mktemp -d)`; the test suite already does
the equivalent for automated runs via `tests/conftest.py`'s autouse
`isolated_data_dir` fixture.

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

**If you're upgrading an existing `library.db`:** the `songs_path_unique`
index above cannot simply be added to a database that predates it, because
`add_song` had no dedup before this task and could already hold two rows for
one path — creating a `UNIQUE` index over duplicate values raises
`sqlite3.IntegrityError` and the server refuses to start. `Store.__init__`'s
`_SCHEMA` therefore runs a migration immediately before creating the index:
for every `path` with more than one row, it keeps the row with the lowest
`rowid` (the oldest import), re-points any `renders` that pointed at a
row about to be deleted onto the surviving one, and only then deletes the
duplicates. This runs on every open and is a no-op once a database has no
duplicates left — including a fresh one. The consequence for an operator who
already ran this server during development: the next time it starts, any
duplicate library entries silently collapse into one (keeping the earliest),
and that song's render history reappears whole under the surviving id rather
than split across two entries. Nothing is deleted from disk — only the
now-redundant `songs` row — so no render file is lost; only the extra
library-list entry pointing at the same path goes away.
`tests/test_store.py::test_opening_a_database_with_duplicate_paths_migrates_it`
exercises this by inserting a raw duplicate row (bypassing `add_song`, the
only way to still create one) and asserting a fresh `Store()` opens cleanly
and re-points the orphaned render.

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

`sleepmix/static/index.html` was, at the end of Plan 2a, a deliberate
placeholder rather than a preview of the finished UI — `app.py` served it at
`/` only so there was something to load in a browser and confirm the server
was up. Plan 3a has since replaced it outright with a compiled Elm
application; see the Plan 3a section above and `ui/README.md`.

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

What still sat beyond both plans at that point: the Elm application itself.
Plan 3a has since built the library view and song view; the mixer, render
screen, schema-driven controls consuming `config_schema()`, and Web Audio
buffer swapping at loop boundaries using `render_window` remain Plan 3b — see
the Plan 3a section above. Segment selection and arrangement, output length as
an arrangement property, and a bundled desktop app are noted in the spec as
future work beyond any plan written so far.

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
by Plan 2b (`feat/interactive-server`) items, followed by Plan 3a
(`feat/elm-shell`) items found during this plan's review.

- **Four things contribute to a render's final peak that `master_gain`'s
  calibration window never sees.** `preview.master_gain` measures one window,
  `render_window(session, 0.0, reverb=<the flag>, master=False)`, and derives
  a gain from its peak. `pipeline.run_pipeline` peak-normalizes something
  rather different, and each difference moves a preview off the render's
  level. Listed by measured magnitude, largest first. All four were measured
  the same way: RMS of a mid-arc mastered preview over the corresponding
  crossfade-free region of a real `run_pipeline` output, default config,
  changing one thing at a time. The baseline — default reverb, `reverb=True`,
  fades off — is **1.0003, +0.00 dB**, and is what `tests/test_preview.py`'s
  `test_a_mastered_preview_sits_at_the_render_s_level` now asserts.

  1. **`_apply_fades` runs before `normalize_peak`, and `fade_in_s` defaults
     to 8 s.** This is by far the largest of the four and was never recorded
     until now. The fade attenuates precisely the region iteration 0
     occupies — the window `master_gain` calibrates against — so the render's
     own loudest moment is somewhere after the fade-in completes, not at the
     start. Measured with the default fades: **0.8107, −1.82 dB**. That is
     thirty-five times the sound bed's contribution, in the direction that
     matters (a preview reading quieter than it should, so *more* decayed).
     It also means **"the first iteration is the loudest" is an over-claim**:
     true of `render_window`'s output, which has no fades, and false of the
     render, which does.
  2. **The inter-iteration `equal_power_crossfade` can sum above a single
     iteration's peak.** Two consecutive decayed iterations overlap for
     `cycle_crossfade_ms`, and their sum in that region can exceed either
     one alone, so `normalize_peak` pulls the whole render slightly further
     down than a one-window calibration predicts. Measured on the dry path
     (`reverb.wet = 0.0`, `reverb=False`): **1.0431, +0.37 dB**, which drops
     to 0.9995 with `cycle_crossfade_ms = 0.0` and nothing else changed —
     so the residual is entirely this. With default reverb it is masked to
     about 0.01 dB, because reverb smears the peak either way.
  3. **`output.sample_rate` is absent from `RenderSession._master_key`,**
     although `run_pipeline` resamples before normalizing. The magnitude is
     small (~0.01 dB at 22050 → 44100 on the test signal), but the *cache*
     consequence is unconditional: changing the output rate does not
     invalidate the memoized gain at all, so a session keeps serving a factor
     measured at the old rate until something else happens to clear it.
  4. **The sound bed is never mixed into the calibration window.**
     `render_window` sums only the configured stems and never calls
     `soundbed.build_soundbed`, while `run_pipeline` adds the bed before
     normalizing. This was previously recorded here as "the most important
     gap left in the level-matching" — measurement says otherwise, and by a
     wide margin. At the default `noise_gain_db = -34` it moves the ratio to
     **1.0031, +0.03 dB**; even at `-6 dB` it only reaches **0.9947,
     −0.05 dB**. The reason it stays inaudible is that `normalize_peak`
     scales the stems down by very nearly the same factor the bed pushed the
     peak up, so the two mostly cancel. `SoundbedConfig.enabled` defaults to
     `False` in any case.

  None of the four is fixed. They are recorded because the sizes are
  counter-intuitive: the one that was written down was the smallest, and the
  largest was not written down at all.

- **Nothing is ever reclaimed, and the one that matters is on disk.** Ranked
  by how much it actually costs:

  **Render output files accumulate forever.** Every completed render writes a
  WAV under the app-data directory and the row keeps pointing at it. There is
  no `DELETE /api/renders/{id}`, no pruning, no size cap and no retention
  policy — the only way to reclaim the space is to delete the files by hand
  and leave the rows dangling (which then 404 on download, the same as a moved
  source file). At the default 20-minute duration, 44.1 kHz stereo float32,
  that is roughly **300 MB per render**. A UI whose whole purpose is to make
  rendering easy to trigger will produce these in quantity; a handful of
  afternoons of tuning is tens of gigabytes. This is the resource problem on
  this branch, and it is several orders of magnitude larger than the two
  below.

  **`JobManager._jobs`, `_tokens` and `_subscribers` are never evicted.** Every
  job ever submitted — every separation, every render — stays in `_jobs` for
  the life of the process, keeps its `CancelToken` in `_tokens`, and holds a
  permanent (if eventually empty) list in `_subscribers`. Kilobytes, not
  megabytes: fine for a session-length local tool that gets restarted often, a
  slow leak for a server left running for days. `_tokens` was omitted from
  this entry when it was first written; it grows in exact lockstep with the
  other two.

  **`SessionRegistry._use_locks` is only cleared in `clear()`.** One `RLock`
  per song id ever previewed, deliberately kept past eviction so a thread
  holding one cannot have it swapped out from under it. A few dozen bytes
  each, bounded by distinct songs previewed in a process — the smallest of the
  three, and noted only so it is not mistaken for an oversight.

- **A `BaseException` escaping a job leaves it stuck at `"running"` forever.**
  `JobManager._run` catches `Cancelled` and `Exception`, but a `SystemExit` or
  `KeyboardInterrupt` raised inside a job function would propagate past both,
  and nothing in `_run` would ever set a terminal status — the job's row (and
  any render or song row it was updating) is left reporting `"running"`
  indefinitely, and the SSE stream watching it never closes.

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
  saved. That made the validation a side effect of a call that looked like
  dead code, one `# unused` cleanup away from being deleted along with the 400
  path it provides; it is now bound to `_validated` with a comment saying so,
  which is a speed bump rather than a fix. Separately: `start_render` *does*
  independently reconstruct
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

- **DNS rebinding is now mitigated by a `Host` allow-list.** Binding loopback
  stops other machines from connecting; it does not stop a web page the
  operator visits from rebinding its own hostname to `127.0.0.1`, at which
  point the page is same-origin with the API and can drive it. That mattered
  more than the earlier note here suggested: it described the consequence as
  "import a path, read the waveform back", which was written when the surface
  was read-only. A rebound page can now also `POST /api/renders` — minutes of
  CPU and a ~300 MB file per twenty-minute request, with no rate limit, no
  quota and no `DELETE` endpoint to undo it.

  `server/app.py`'s `_HostAllowList` rejects any request whose `Host` is not
  on the list with a 400, before any route runs. Rebinding needs DNS, so such
  a request always carries the attacker's *hostname*; that header is the one
  thing that distinguishes it from a genuine local request. The list is a
  `create_app(allowed_hosts=...)` parameter defaulting to `localhost`,
  `127.0.0.1`, `::1` and `testserver` — the last being the `Host` FastAPI's
  `TestClient` sends, which was the whole reason this was previously deferred.
  `cli.py` appends the bound host, so `--allow-remote --host 192.168.1.5`
  still answers to itself; a wildcard bind (`0.0.0.0`, `::`, `""`) passes
  `["*"]`, because it cannot enumerate the names it is reachable by, and that
  path is already explicit informed consent.

  It is written here rather than using Starlette's `TrustedHostMiddleware`,
  which was the obvious choice and does not work: that middleware extracts the
  host as `header.split(":")[0]`, which yields `"["` for `[::1]:8765` and `""`
  for a bare `::1`. An IPv6 literal therefore cannot be allow-listed there in
  any spelling, and `sleepmix ui --host ::1` — supported, tested, and opening
  `http://[::1]:8765/` in the browser — would have 400'd every request from
  the operator's own machine. `_host_without_port` handles the bracketed form;
  `tests/test_server_app.py` covers each shape.

  This is host filtering, not authentication. It stops a rebound page; it does
  nothing about anyone who can already reach the port and send a correct
  `Host`. The path allow-list noted above is still the thing that would make a
  non-loopback bind genuinely safe, and still does not exist.

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

- **`ui/hash_sources.py` orders its inputs by sorted path**, so a module
  rename that happened to change the sort order while every file's total
  content stayed byte-identical would not change the recorded hash. Fine for
  what it's used for — noticing that `ui/` changed and `app.js` wasn't
  rebuilt — but it is a drift detector, not a proof that the bundle is
  reproducible from its sources.

- **`Api.elm`'s `stems` decoder combines `Pipeline.optional` with a
  nullable-then-`withDefault` inner decoder.** Correct — a missing or `null`
  `stems` field both end up as `[]` — but redundant: `Pipeline.optional`
  already handles the missing-field case, so the inner `Decode.nullable`
  layered on top only ever does anything for an explicit JSON `null`, and the
  server never sends one.

- **No direct test exercises `SeparationFailed` on the song side.** `Api.elm`'s
  `SeparationFailed` variant of `SeparationStatus` is only exercised
  indirectly, via the job decoder's `Failed` variant on the job-status enum,
  which is a different decoder over a different field.

- **`Main.routeFor` is still only exercised indirectly.** `ui/tests/` now
  covers `Api`'s decoders, `Main`'s job state machine and `update` transitions,
  `Page.Song`'s `needsForce`/`buttonLabel`, `Page.Library`, and
  `Waveform.barFor`. No view is tested — deliberately — and `routeFor`, which
  is one `case` over a `Maybe`, is reached only through them.
