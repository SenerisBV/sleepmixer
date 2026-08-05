# Project state

Status as of the end of the `feat/presets` branch (Plan 3d of the spec, all
6 tasks complete), on top of `feat/render-queue` (Plan 3c, all 9 tasks
complete), on top of `feat/mixer` (Plan 3b, all 7 tasks complete), on top of
`feat/elm-shell` (Plan 3a of the spec, all 6 tasks complete), on top of
`feat/interactive-server` (Plan 2b, all 8 tasks complete),
`feat/server-foundation` (Plan 2a, all 7 tasks complete), and `feat/core-hooks`
(Plan 1, all 10 tasks complete). Plan 1 gave the pipeline the hooks a local web
UI needs — session staging, cheap preview, structured progress, stable data
paths, a config schema — without building the UI itself. Plan 2a put an HTTP
server in front of that: a FastAPI app, a SQLite library store, and enough of a
songs API to import a file and draw its waveform. Plan 2b built the rest of the
API: preview, background jobs with live progress and cancellation, renders, and
presets. Plan 3a is the first real frontend — an Elm application replacing the
placeholder `index.html` — and it is scoped to *browsing and separating*, not
yet to mixing or rendering. Plan 3b adds the mixer: controls generated from the
config schema, a scrubber over the decay arc, and audio that plays while you
shape it. Plan 3c makes a running separation genuinely stoppable (previously
only a render could be cancelled mid-flight; Demucs's own call was a single
opaque block nothing could interrupt), and it gives the interface the three
things Plan 3b's own closing section named as still missing — a render
screen, a queue screen, and a warning before a job large enough to block
everything behind it. Plan 3d is the subject of this section: it gives
presets a screen — `server/api/presets.py`'s CRUD had been reachable only with
`curl` since Plan 2b — adds `PUT /api/presets/{id}` so one can be renamed or
saved over instead of only ever created fresh, and closes a gap this document
used to carry as open by adding `GET /api/config/default`, the route that lets
a freshly opened mixer start from the same curated per-stem values
`sleepmix render` does rather than from the schema's one identical setting for
every stem. Read `docs/architecture.md` first for how the pieces fit
together; this document is about what's true right now, what was traded off
to get here, and what's explicitly not done yet.

## Plan 3d: presets, and the server's own defaults

Two gaps closed together, because the same mechanism closes both: a preset is
a named config snapshot, and the server's own defaults are values with
nowhere to live *as* a config until the mixer already knows how to accept
one.

**The mixer used to start every stem identical, which was a real audible
difference from what `sleepmix render` produces by default — closed by this
plan's `GET /api/config/default`.** A fresh mixer built `Config.fromSchema`
from `/api/schema` alone, and the schema has no way to describe a list, so it
could describe every stem's bounds but not that the shipped default has
`drums` off, `bass`'s decay off, `vocals` dissolving on an `exp` curve to
2200 Hz, and `other` to 2400 Hz — the curated shape `MixConfig`'s own
dataclass defaults carry. This document used to record that divergence in
detail, stem by stem, as an open gap under Plan 3b, with a note that closing
it properly needed the server to publish its own default config rather than
a copy of that list written out in Elm. `GET /api/config/default`
(`dataclasses.asdict(MixConfig())`, see `docs/architecture.md`'s new section
on it) is exactly that: a mixer now opens with the same starting point a
render does, and `Config.overlay` — the same function that lays a preset
over a config — is what turns those published values into one, so applying a
preset and loading the server's own defaults are one code path rather than
two that could drift apart.

**Presets can now be renamed or saved over, and a preset saved under its own
existing name is not treated as though it collided with itself.**
`PUT /api/presets/{id}` (`server/api/presets.py`) validates exactly as
`POST` does — a config that could never render is refused with a 400 before
it is stored, not discovered later at render time with the connection to the
bad value already lost — and checks the name collision explicitly rather than
catching the database's own `UNIQUE` violation, because the unique index
cannot tell "this name is taken by someone else" from "this name is taken by
the row being updated," and the second is the ordinary case of saving a
preset over itself. See `docs/architecture.md`'s new section for what a
preset deliberately still does not carry (the song's own loop region,
`separation_model`) and why.

**The mixer's preset bar (`ui/src/Page/Mixer.elm`)** is a row above the
controls, not a screen: choose a preset from a select, Apply it against the
song currently open, type a name and Save as a new one, Save over the
selected preset, or Delete it. Applying a preset means *make it look like
this*, not merge it in — a field the preset doesn't mention goes back to its
schema default, not to whatever the operator had it at a moment ago — except
the song's current loop region, which is carried across explicitly because a
preset never carries loop seconds belonging to a different piece of audio
(`Page.Mixer.applyPreset`, `docs/architecture.md`).

**`songs.last_preset_id` remembers which preset was last applied to a song,
as a hint and nothing more — deliberately never applied automatically.**
Reopening a song's mixer always starts from the server's own defaults; any
preset that had been applied to it has to be chosen again, from a line
reading "last used here" beside an Apply button. Auto-applying it was
considered and rejected: a preset is a shared, editable recipe, and a mixer
that silently re-applied one on open would mean that editing a preset later
silently changes the sound of every song ever pointed at it — including one
tuned and considered finished weeks earlier. `PUT
/api/songs/{id}/last-preset` records the id and nothing more; nothing reads
it except that one line of UI.

That id is deliberately not a foreign key, and deleting a preset a song
points at is an ordinary, unremarkable thing to do — verified directly this
task: deleting a preset a song's `last_preset_id` still names leaves the
song row holding the now-dangling id, `GET`s it back with no error, and the
mixer's own lookup against the (now shorter) presets list simply stops
finding it, so the "last used here" line quietly stops appearing. No
migration, no constraint, and no 500 anywhere in that path.

**What the final whole-branch review changed.** (1) `Mixer.applyPreset` built
its base from `Config.fromSchema` alone rather than sharing `Mixer.init`'s
base (schema defaults overlaid with the published ones) — the two agreed on
every scalar leaf, because a schema default already equals the dataclass
default, and diverged in exactly the one place `MixConfig` curates a list the
schema cannot describe: the stems. A preset silent about a stem, or applied to
a song whose stems didn't match the ones the preset was saved from, fell all
the way back to the schema's uniform values — drums enabled, vocals on the
wrong curve — with `defaultsNote` staying silent, because the defaults *had*
arrived. Fixed by pulling the shared base into `Mixer.baseConfig`, used by
both `init` and `applyPreset` now, with `Main`'s one production call site
threading `publishedDefaults model.defaults` through. (2) `GotDefaultConfig`'s
error branch unconditionally overwrote `model.defaults` with
`DefaultsUnavailable`, which used to be harmless because the fetch only ever
happened once per session; now that `OpenMixer` re-issues it on every open, a
transient failure arriving after an earlier fetch had already succeeded could
discard a `DefaultsReady` value that worked, regressing every later mixer in
the session to the schema's bare defaults for no reason a fetch failure this
time actually caused. Only `DefaultsLoading`/`DefaultsUnavailable` now move to
`DefaultsUnavailable` on error; `DefaultsReady` stays exactly as it was. (3)
That same overwrite was the only way `defaultsProblem`'s "could not be
fetched" sentence could render under a mixer that had, in fact, opened with
the real defaults — (2)'s fix closes this too, confirmed by reverting just
that guard and watching the contradiction reappear, not assumed. (4)
`applyBlock`'s "Choose a preset to apply" used to show beside a fully live
`lastUsedLine` Apply button whenever the preview was playable and nothing was
picked from the dropdown — that Apply needs no selection at all — reading as
if neither button worked; it now names the "Last used here" line as the live
alternative when one exists for the song. (5) Five stale documentation claims
about presets and the server's defaults, mostly found while tracing (1)
through the docs that describe it, are corrected in `README.md`,
`ui/README.md` and `docs/architecture.md`: an undercount of `setLastPreset`'s
call sites, an "always" a failed fetch actually falsifies, `other`'s decay
curve misattributed as `exp` when it is `linear`, a docstring pointer that
says nothing about what it's cited for, and a preset-save network-error
branch that does not exist in the suite.

**Five small things this plan's own reviews found and left, none of them
blocking:**

- **A check-then-act race survives in `_migrate_last_preset_id`** (added to
  `Store.__init__` to add `songs.last_preset_id` to a database that predates
  it). Two processes opening the same pre-migration database in the same
  instant could both see the column missing and both try to add it; the
  loser raises `sqlite3.OperationalError: duplicate column name` at startup.
  `Store` is a per-app singleton and this is a single-user desktop tool, so
  the failure mode is the loser crashing once and self-healing on the very
  next retry (the column exists by then) rather than any lasting
  inconsistency — ruled not worth a lock for.
- **`test_update_preset_keeping_its_own_name_is_not_a_collision` does not
  prove what its own docstring claims.** It was written to show that the
  explicit `AND id != preset_id` pre-check (`Store.update_preset`) is what
  lets a preset be saved over itself under its own name; a version that
  instead saved first and caught the database's `IntegrityError` passes the
  same test, because SQLite's `UNIQUE` constraint never fires on a
  self-rename regardless of which style wrote the check. The test does have
  real value, verified by mutation — it does catch forgetting the `AND id !=
  preset_id` clause itself — the docstring's claim about *why* is simply
  broader than what the test can tell apart.
- **`ui/tests/ApiTest.elm`'s pre-existing unknown-status test omits
  `last_preset_id` from its fixture entirely and still passes** — only
  because the decode fails earlier, on the deliberately-bad
  `separation_status` the test exists to exercise. Harmless, and untouched by
  this plan, but nobody should read the omission as evidence the field is
  optional; `Api.Song`'s decoder requires it.
- **No `RequestTest.elm` exists**, so this plan's new `Request` functions —
  their paths, verbs, and JSON encoding — are exercised only by reading, the
  same as every other function in that module. Pre-existing convention, not a
  gap this plan introduced.
- **Nothing in either suite exercises `Config.overlay` against the *real*
  schema or the *real* published defaults, and the final review's Fix (1)
  above is exactly what living in that gap costs.** `ui/tests/Fixtures.elm`'s
  schema is a trimmed hand-copy of one live `GET /api/schema` response, with
  no `reverb` section and no `search_end`; the Python side's own test of
  `GET /api/config/default` stops at `MixConfig.from_dict(body) ==
  MixConfig()` and never reaches Elm at all. So the branch's headline claim —
  that a mixer opens on the same values `sleepmix render` would use — held,
  through six per-task reviews and two earlier whole-branch fix-wave attempts
  that also missed it, only because `Fixtures.elm`'s schema and the server's
  real one happen to agree with each other, not because either is ever
  checked against the other's ground truth. `MixerTest.elm`'s `onDefaults`
  fixture (three tests use it) is the closest either suite comes, and it is
  still a hand-written `Decode.Value` standing in for the real route.
  Closing this needs one fixture generated on one side — a real
  `GET /api/schema` and a real `GET /api/config/default` response, captured
  once against a running server — and consumed unmodified by the other side,
  the same shape `_ui_body` (Plan 3b, above) still lacks for `Config.encode`.
  Not attempted here.

**What this plan does not cover, named up front rather than discovered
later:** a presets screen (list, browse, delete from outside the mixer),
preset import or export or sharing between installations, and migrating
`last_preset_id` to an enforced foreign key. Segment selection and
arrangement, a path allow-list for `import_song`, streaming peak
computation, and authentication are carried forward unchanged from earlier
plans — see "Known weaknesses, deferred deliberately" below.

## Plan 3c: jobs you can watch and stop

The incident this plan exists to fix: a seventy-minute file, imported by
accident, that the operator wanted to test a smaller one instead of — and had
to kill the server by hand to get at, because nothing running could be
stopped and nothing on screen showed what was queued behind it. It turned out
to be suspended (`Ctrl-Z`) rather than dead, and was found still holding
6.2 GB resident. Plan 3c closes every part of that: separation can now be
cancelled mid-run, a queue screen shows what the one worker is doing and
what's waiting, and both the mixer's Render button and the song screen's
Separate button say so before a long source file is submitted.

**Separation is killable now, and the mechanism is a subprocess.**
`demucs.apply_model` is one opaque call that never looks at a cancel token, so
making it interruptible meant moving it out of the request-serving process
entirely: `separation_process.run_separation` runs `python -m
sleepmix.separation_worker` as a child, reads its phase progress off stdout,
and kills it (`SIGTERM`, escalating to `SIGKILL`) the moment a cancel token
fires. See `docs/architecture.md`'s new section on this for the phase
protocol and — the part that mattered most in review — how the three ways a
child process can end (cancelled, crashed, "demucs isn't installed") are kept
from being read as each other. This task's own verification confirmed it
against a real 246.6 s track and a real Demucs run: cancelling partway through
(at `fraction=0.15`, mid-"Separating stems") left the song back at `pending`
with no reason recorded, no worker process still running, and **nothing at
all** in the cache directory — not a partial stem, not a staging directory.

**The stem cache write became atomic as a consequence, not a separate
goal.** A subprocess that can be killed can be killed mid-write, and the old
two-step cache write (marker, then stems, straight into the final directory)
had no atomic "finished" to interrupt. `separation._write_cache` now builds
everything in a sibling staging directory and renames it into place in one
step, so a kill lands either before the rename (nothing changes) or after it
(the new cache is already complete) — never in between. See
`docs/architecture.md` for the full reasoning, including why the old ordering
was right for the write that used to exist and stopped being relevant once
that write did.

**The render screen (`Page.Renders`)** shows every render — queued, running,
done, cancelled, failed — with a config summary (duration, which stems,
where the decay ends up) read from whatever was actually `POST`ed rather than
inventing a value for fields the server defaulted silently. It plays a
finished render through a plain `<audio controls>` element rather than the
Web Audio port the mixer uses, deliberately: the port decodes a whole buffer
into memory to loop it on a musical seam, which is the wrong trade for half an
hour of audio a browser will happily stream instead. A render still running
gets a Cancel button and a progress bar fed by the same job machinery
separation uses; a finished one gets a download link and a Delete button, and
deleting removes both the database row and the file on disk, verified this
task by watching both actually disappear.

**The one bug this screen shipped with and caught in its own review is worth
keeping the story of.** The first version paired a render with its progress
job by *song and timestamp*, a heuristic standing in for a real key — and a
render row stranded at `"running"` by a server restart (rows are in SQLite,
jobs are only ever in memory) would silently adopt the *next* render's job the
next time that song was rendered. Clicking Cancel on the dead row would then
kill the live render underneath it, and `_abandon` would delete its partial
file — the wrong render, stopped, invisibly. The fix was a real key:
`Job.render_id`, three server lines, flowing through `GET /api/jobs`, the SSE
stream and the render POST response, with the heuristic deleted outright
rather than kept as a fallback — a fallback that silently mispairs is the bug,
not a safety net for it.

**The queue screen (`Page.Queue`)** answers "what is the one worker doing, and
what's stacked up behind it" — running first, then queued, then what recently
finished, oldest first within each group because that is the order the worker
will actually take them in. It is live-only and says so: `JobManager` keeps
jobs in memory, so a restart empties this screen, and an empty screen is then
the truth rather than a failure to load. It polls `GET /api/jobs` every four
seconds rather than streaming, because ten rows streaming one worker's
progress each would be ten connections answering the same question `Page.Queue`
already asks once. Every non-terminal row has a Cancel button, including a job
still *queued* — which, on this project's one worker, might mean waiting
behind a separation that runs for many minutes, and used to mean nothing
visibly happened when you clicked it (below). Cancelling a queued render
settles its row immediately rather than leaving it to a work function that
will now never run (see the note on `JobManager.cancel` below); the same
route settles a render cancelled while queued even if nothing else ever
touches its row again, which is what makes it deletable afterwards instead of
stuck forever at a status `DELETE` refuses.

**A cancel on a queued job used to be completely silent, in exactly the
scenario this plan exists for.** `JobManager.cancel` only set the token;
the status only flipped once the pool actually reached that job, which on one
worker means after whatever is running ahead of it finishes. Seventy-minute
separation running, a render queued behind it, operator clicks Cancel: the
response said `cancelled: true`, and the row went on reading "waiting" for
seventy minutes, because nothing was wrong with the cancel — it had just not
had a chance to matter yet. The fix flips a **queued** job's status to
`cancelled` synchronously, inside the same lock, the moment `cancel()` is
called, since `_run`'s own guard means that job will never do any real work
regardless. A **running** job is left for its own work function to settle,
because settling it from the request thread as well would race the worker —
the case that would hurt is a render finishing a moment after the token was
set, where the request thread's write could land "cancelled" over a row the
pipeline had just, correctly, marked "done".

**`Warn` is one module, not a sentence written twice.** The mixer's Render
button and the song screen's Separate button both put work on the same
single worker, and a warning written once in each place is a warning that can
drift into disagreeing about the same queue. `Warn.forSource` names a
duration (rounded to the nearest minute, with "roughly" doing the work of not
claiming a precision that isn't there) once source audio passes fifteen
minutes — a judgement call, not a measurement: roughly three times an ordinary
album track, and nowhere near either side of the incident it exists to catch.
It warns; it does not block, because a long file is a legitimate thing to
render and the threshold exists to catch the accident, not to have an opinion
about long songs.

**`Warn.forSource` keys on the source file's length, and that is a real gap a
render's own timing now makes concrete.** A render's wall-clock cost is
dominated by `output.duration_min`, not by how long the source track is — this
task's own measurement found a 246.6 s source with its stems already cached
rendering to the default 20-minute (1200 s) mix in roughly 11–14 s (measured
twice, 11.0 s and 13.6 s; see `docs/architecture.md`),
because the cost that scales with output length (`build_disintegrating_stream`
iterating roughly seventy times for that loop) is cheap per iteration, while
the cost that would actually make a render slow — separation, which does scale
with source length — has usually already been paid by the time the mixer's
Render button is reachable at all. Read backwards, that means the warning is
watching the wrong number for what it is nominally about: a four-minute source
rendered to a **sixty-minute** mix (`output.duration_min = 60`, a config change
away, not a different file) would iterate roughly three times as many loops as
the measurement above and block the one worker for a correspondingly longer
stretch, and nothing would warn, because the source is nowhere near fifteen
minutes. The warning was written before anyone had a render-timing number to
design a better one from; it now exists, and extending `Warn.forSource` (or
splitting it) to also look at the configured output length is the natural next
move, not attempted here because this task writes no application code.

**Known gaps, carried forward rather than fixed:**

- **A sub-millisecond TOCTOU race survives in the duplicate-separation
  guard.** `separate_song` checks `jobs.list()` for an in-flight separation on
  the same song before submitting a new one, but Starlette dispatches sync
  routes on a threadpool and nothing locks read-decide-submit as one
  operation. Two genuinely simultaneous `POST /separate` requests could still
  both pass the check and stack two jobs. Ruled not worth fixing: the guard
  exists for a job sitting queued for *minutes* behind a render, a window any
  request landing anywhere inside easily sees, and the residual worst case —
  two duplicate jobs — is exactly the pre-fix status quo rather than a new
  failure mode.
- **`terminate()`/`kill()` only signal the direct child**, so a grandchild
  process would survive being orphaned if Demucs ever spawned one. It doesn't
  today — this project's `apply_model` call passes no worker processes — and
  `start_new_session=True` plus `os.killpg` carries platform nuance not worth
  adding speculatively against a case that doesn't exist yet. Revisit if
  Demucs configuration ever gains worker processes of its own.
- ~~**No automated test asserts that a cached *fallback* separation still
  reports itself as a fallback through the supervisor's warm path.**~~ Closed
  by the final fix wave:
  `test_a_cached_fallback_still_reports_itself_as_a_fallback` writes a fallback
  cache, calls `run_separation`, and asserts the reason survives. It was worth
  closing rather than carrying: the warm path returns
  `SeparationResult(_load_cache(…), _load_fallback_reason(…))` directly instead
  of going through `separate_detailed`, deliberately, so it is a second place
  that has to remember — and forgetting makes a song separated before Demucs
  was installed read as properly separated, with per-stem controls implying a
  separation that never happened.
- **No `update`-level test covers the renders fetch flow.**
  `GotRenders`, `GotRenderJobs` and `refreshRenders` appear nowhere in
  `ui/tests`, so the fetch-ordering fix described above (and the stale-jobs
  handling around it) is verified by reading the code, not by a test that
  would fail if it regressed. `OpenRenders` itself does appear —
  `UpdateTest.elm:439,442` drives it, but only incidentally, to assert the
  queue and renders screens are never both open at once; nothing there
  exercises the fetch it triggers. The final fix wave narrowed this rather than
  closing it: the screen's Cancel wiring is now asserted through `Main.view`
  (`RendersTest.elm`, "the Cancel button, through the whole application"),
  because that one control can destroy something and `jobFor` alone could not
  vouch for it. The rest of `Page.Renders`' and all of `Page.Queue`'s view
  markup is still unasserted. Relatedly, `keepStreamed` pins the
  held copy of a streamed job unconditionally, so a poll can never correct it
  once it's set — safe today only because every server-side update publishes
  to every subscriber, so the held copy and a poll's copy never actually
  disagree in practice.
- **The download filename is the render's hex id.** `Page/Renders.elm`'s own
  docstring opens by naming this as the very problem the screen exists to
  solve — finding a render afterwards used to mean `ls` and a filename that
  says nothing — and the downloaded file still has one, even though the
  screen has the song title sitting right next to the Download link. A
  deliberate UX call parked rather than a defect: fixing it is a `Content-
  Disposition` filename away, not attempted here.
- **`.queue-head` overflows horizontally below an estimated 400px.**
  `.queue-kind` carries an unshrinkable `flex: 0 0 5.5rem` and the status and
  timestamp are `nowrap` — a real bug class, but "roughly 400px" is a figure
  read off the CSS rule, not a measurement taken in a browser; nobody in this
  project's review loop can open one. Cosmetic on a desktop-only local tool —
  `.renders` already has the same class of thing — and not fixed here.
- **`JobManager.cancel`'s docstring used to claim only two orderings were
  possible** between a cancel and the worker starting the same job — this one
  wins and `_run` short-circuits into its own cancelled update, or `_run` wins
  and this sees `"running"` and defers to the work function's own `check()`.
  There is a third: `_run` reads `token.cancelled` without holding the lock,
  so a worker that read `False` a few microseconds before `cancel()` acquires
  the lock can still go on to write `status="running"` over the `"cancelled"`
  that was just set. It self-heals — the token is already set by the time
  that happens, so the work function's own `check()` raises almost
  immediately and `except Cancelled` restores the status — and it needs the
  previous job to finish inside that same handful of microseconds, so no
  permanent inconsistency results. The docstring is corrected to not claim an
  exhaustiveness it doesn't have; the behaviour itself is unchanged.
- **A render against an unseparated song still separates in-process, where
  the cancel token cannot reach Demucs.** Separation is killable for the
  standalone Separate action, and for renders started from the mixer, which
  requires prior separation before it will even open. But `POST
  /api/renders` does not require that — it is reachable directly, bypassing
  the UI's own gate — and `start_render`'s work function calls
  `run_pipeline`, which calls `separation.separate()` directly rather than
  the subprocess-wrapped `separation_process.run_separation`. That predates
  this branch and is out of scope to change here, and nothing in this
  document or `docs/architecture.md` claims otherwise — but it is a real
  residual, the same shape as the seven above it: a render submitted this way
  against a song with no cached stems is cancellable only at `run_pipeline`'s
  own checkpoints (`docs/architecture.md`'s "Progress and cancellation
  contract"), all of which come *after* separation returns, so the one
  worker is committed to a full, uninterruptible Demucs run before the first
  checkpoint is even reached. A maintainer closing this would route that call
  through `run_separation` instead of `separate`, threading through the
  `reporter` and `cancel` that `run_pipeline` already has in scope — the same
  two arguments `separate_song`'s own `work` function already passes to
  `run_separation` today.

  **The preview path reaches the same call, and that is what made this
  UI-reachable rather than curl-only.** `RenderSession.stems()`
  (`sleepmix/session.py`) also calls the in-process `separation.separate()`, so
  the first preview on a song with no cached stems runs a full Demucs inside
  `SessionRegistry`'s per-song use lock, holding a threadpool thread, with no
  job, no queue row, no Cancel and an indeterminate "Preparing…" panel. Every
  door into the mixer is gated on `song.stems` being non-empty, which is what
  normally keeps that call unreachable — see the invariant below, which is the
  thing that gate depends on and which this branch briefly broke.

**The invariant `songs.stems` carries, added by the final fix wave:**

`songs.stems` and the on-disk separation cache are two records of one fact, and
after Plan 3c they can be written at different moments. Only one line can make
them disagree — the `invalidate_cache` inside `separate_song`'s work function,
which `force=true` reaches — and it now clears `stems` in the same breath.

The rule is: **from the moment the cache is deleted until the moment new stems
are written, the row says the song has none.** Nothing else in the codebase
deletes a cache while a row survives it.

This is not bookkeeping. Every gate into the mixer reads `song.stems` and not
the cache — `Page.Song.mixerPanel` for the button, `Main`'s `OpenMixer` for the
model, deliberately, because the client cannot see the disk. Before the fix, a
forced retry that was cancelled (newly possible from the queue screen) left a
row reading "not separated" *and* listing four stems *and* offering an enabled
Open-the-mixer with no explanatory line. Opening it did the two worst things
available here: the in-process Demucs run described above, and then — once it
cached four real stems while the mixer's rows had been built from the stale
list — a `plan_stem_configs` that matched none of them and returned every
available stem at its defaults, silently discarding every gain, reverb send and
decay setting on screen.

Every task on the branch was individually right. The cancel path is correct to
reset only the *status*; the atomic cache write is correct and is precisely why
force leaves nothing on disk; making a running separation cancellable is what
makes the sequence occur at all; and gating the mixer on `song.stems` was right
back when stems and cache could only ever be written together. Nobody owned the
sentence that has to be true across all four, which is why it is written down
here rather than left to be re-derived.

`tests/test_api_songs.py` holds it as a sequence rather than a unit —
`test_cancelling_a_forced_separation_leaves_the_song_with_no_stems` and
`test_a_forced_separation_that_fails_also_leaves_no_stems` — because no single
step is wrong and only the order is.

## Plan 3b: the mixer

`ui/src/Page/Mixer.elm` is the screen the previous two plans were building
toward — a progress scrubber over the decay arc, per-stem enable/gain/reverb-
send/decay, solo, and the loop region drawn on the waveform with its tempo. It
is reached from the song screen and it plays: `ui/ports/audio.js` fetches
`POST /api/preview`, decodes the WAV and loops it, swapping buffers at the next
loop boundary.

Almost none of the controls are written. `GET /api/schema` describes every
config field and `ui/src/Config.elm` holds the values and re-nests them for
`MixConfig.from_dict`; `Config.elm` names no config parameter at all, with
three structural exceptions it documents, and `Page/Mixer.elm` names a handful
that are not controls (`separation_model`, which it deliberately withholds a
control from; `output`/`duration_min` for the scrubber readout;
`loop`/`start_s`/`end_s`, the two the loop endpoint takes an override for; and
the sections that get an explanatory note), each argued for in a docstring
where it appears. Adding a field in
`sleepmix/config.py` puts a control in the mixer with no frontend change. The
same reasoning went the other way once during this task: `MixConfig.seed` now
carries `min: 0` in its metadata, because `validate` rejects a negative seed and
the UI's bounds come from the schema alone — without the floor, a generated
control could produce a config the server refuses, and it would surface as a
400 on a preview rather than as a slider that will not go there.

What it does not do yet, and what to know before changing it:

- **The sound bed is not in previews.** `preview.render_window` does not add it;
  `pipeline.run_pipeline` does. The section says so in place, because otherwise
  you turn on binaural beats, hear nothing, and conclude the mixer is broken.
- **The mixer will not open without stems, or while a separation is running.**
  Its rows *are* the stems, and a preview of an unseparated song would run
  Demucs inside the preview lock with nothing reporting progress. A separation
  finishing also discards the warm session and can change the stem list under
  an open mixer, which is the other half of the gate.
- **"Preparing…" is indeterminate on purpose.** The first preview is the
  slow path — separation if nothing's cached, then finding the loop and
  time-stretching every stem, then the render itself, all behind one lock —
  and nothing in it reports progress, so the bar animates and claims nothing.
  Measured at 117 s / 180.55 s on two different tracks (`docs/architecture.md`
  has the breakdown); the number moves with track length, the absence of
  progress reporting does not. Do not replace it with a fraction; there is
  no fraction. If
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
  `Cmd.none`, or `leaveMixer` omitted `stopPreview ()`, would pass every Elm
  test in the suite — every assertion in `MixerTest.elm` and
  `PreviewTest.elm` is on the model half of `update` (what state `Preview.request`/`Preview.arrived`
  produce), never on whether a real `Cmd` actually left the program and
  reached `audio.js`. Compensated by manual `curl` against a running server
  during this task's own review, not fixed — the gap is structural (Elm
  offers no way to inspect a `Cmd` from a test) rather than a missing
  assertion someone forgot to write, so closing it would need a different
  testing approach, not more tests of this shape.
- **A config that asks for no stems is refused, on both paths — fixed in the
  final review wave, and worth keeping the history of.** `plan_stem_configs`
  used to answer an empty plan with "every available stem at defaults". That
  fallback was written for one case: separation fell back to a single `mix`
  stem, so no configured stem *name* matches what exists, and rendering nothing
  would be wrong. It could not tell that apart from *every matching stem
  switched off* — which was unreachable until this plan shipped a per-stem
  Enabled checkbox. Four clicks reached it, and the preview came back as the
  **full default mix at full level**: `master_gain` recalibrates from the same
  fallback set, so it played at the ceiling, with every gain, reverb send and
  decay curve the user had tuned discarded in the same step. Measured against
  the suite's `stub_separation`: default rms 0.298, all-off rms 0.194 — audible
  music, not silence.

  The two conditions are now separate. "The config describes none of these
  stems" still falls back; "every one of them is off" plans nothing, and
  `plan_stem_configs` may legitimately return `[]`. Both callers refuse it:
  `preview.render_window` raises `NothingToRender` (a `ValueError` subclass, so
  the CLI handles it with every other bad config, and its own type so
  `POST /api/preview` can answer 400 with the reason for *this* without turning
  an arithmetic error from deep in the DSP into a message about stems), and
  `pipeline._plan_jobs` raises the same rather than writing half an hour of
  peak-normalized silence to disk. The one-frame `silence(1, …)` that used to
  end `render_window` is gone; the branch is unreachable and raises.

  The same refusal covers soloing a stem the render would drop, which was the
  48-byte-WAV finding from Plan 3b's verification pass. Both orders are now
  closed in the UI as well: the Solo button is disabled on a switched-off stem
  (as before), and `toggleField` clears the solo when the stem being switched
  off is the soloed one — unrepresentable rather than merely reported. And
  `Main.withMixer` consults `Mixer.everyStemDisabled` before sending, so
  unticking the last stem produces a line on screen saying there is nothing to
  render (the previous preview keeps looping) instead of a request that comes
  back 400 and reads as the server breaking.

  **Why it survived seven task reviews is the part worth remembering.** Neither
  diff was wrong: the Elm generated the checkbox correctly, and `config.py`'s
  fallback was correct when written. The defect lived in the seam — the config
  the mixer builds and the config the renderer consumes were tested
  independently and never against each other. The Elm suite stopped at
  `Config.encode`, the Python suite started at a hand-written dict, and no test
  had ever POSTed a body with a `stems` list in it. `tests/test_api_preview.py`
  now has `_ui_body`, which builds a request shaped exactly as `Config.encode`
  emits one, and asserts a per-stem edit reaches the audio.
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
- This plan's own closing section named four things out of scope: **the
  render screen (start, watch, cancel, download), the presets UI, queue
  visibility, and a warning before importing a file large enough to block
  everything behind it.** Plan 3c closed three of the four — the render
  screen, queue visibility, and the warning, plus, not asked for by this list
  but the same shape of gap, the ability to cancel a *separation* once it has
  started. Plan 3d has since closed the last one — the mixer's preset bar;
  see that section above. Per-song config memory, named in the same breath as
  presets when this was written, turned out to be a different thing than a
  missing screen: Plan 3d considered it and rejected it deliberately (see that
  section), rather than building it.
- The parked defect from Plan 3a is untouched: reloading mid-separation shows an
  enabled button reading "Separating…", because the disable comes from client
  state and the label from the server's status. The mixer's own gate reads the
  server status as well as the flag, so it does not inherit the bug.

**What the final whole-branch review changed**, beyond the empty-plan refusal
above. (1) `toggleField` clears a solo on the stem being switched off, closing
the second of the two orders that reached a mix of nothing. (2) `output.
sample_rate` gained the `sectionNote` the other preview-ignored fields already
had: `render_window` uses the loop's own rate and only `pipeline` resamples, so
that select changes nothing you can hear until you render. (3) The stale
"117 seconds / 73 milliseconds" pair is gone from the four source comments that
still carried it, pointing at `docs/architecture.md`'s reconciliation rather
than repeating a figure measured on a different track. (4) `.back` was styled
under `.song-view` only and is emitted under `.mixer` too — see the scope blind
spot noted in `ui/README.md`. (5) Three test gaps, each of which had let a real
defect through: no test drove `SoloToggled`, `FieldChanged` or `FieldToggled`
through `Main.update` (all three could be stubbed to `( model, Cmd.none )` with
the suite green); no test ever POSTed a body containing a `stems` list; and no
test set a *valid* value on a `StringChoiceField`, an `IntChoiceField` or a
`TextField`, so `parse` returning `Nothing` for a choice field would have left
every `<select>` in the mixer silently deleting its key. All three are closed
and each was verified by mutation. (6) Two route tests asserted only that two
responses differed, which a 422 satisfies as well as two mixes do; they now
assert the status too.

**Four residuals the re-review left open**, none of them blocking, all worth
knowing before you touch this area:

- **`_ui_body` is hand-written, not derived from `Config.encode`.** It is
  shaped exactly as the Elm encoder emits one today, and it does prove
  `MixConfig.from_dict` reads a `stems` list — but nothing mechanically ties
  the two. Rename a key in `Config.elm` and both suites stay green while the
  real request 422s. The seam that produced the empty-plan defect is narrowed,
  not closed; closing it needs a fixture generated from one side and consumed
  by the other.
- **`NothingToRender` reaches the CLI as a traceback, not a message.**
  `cli.py` catches nothing, so `sleepmix render` with every stem off exits 1
  with a Python stack and the reason legible at the bottom. A negative seed
  already behaves this way, and no wrong audio is produced, so it is polish
  rather than a defect. Note also that `_plan_jobs` refuses *after* separation,
  because stem names do not exist before it — a CLI render with everything off
  still pays for Demucs before being told no.
- **A soundbed-only mix is now inexpressible.** Every stem off plus the bed on
  is refused. It never worked before either — it played the full default mix
  *plus* the bed — so this is not a regression, but the door is now explicitly
  shut rather than accidentally ajar.
- **The blocked send does not touch `model.preview`.** If a request is already
  `Queued` when the last stem is unticked, that queued request still goes out
  when the in-flight one returns, so what you hear can be one config-step newer
  than "what you can still hear is the last preview" implies. Harmless — it is
  a mix the user asked for a moment earlier — but the copy is imprecise.

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

**What this section originally listed as not done yet — Plan 3b has since
closed most of it.** Audio playback, orphaned `running` rows, the loop region
and its endpoint, the mixer, preview playback, and schema-driven controls are
all closed now; each entry below is written in the past tense, names what
closed it, and keeps whatever reasoning is still worth having on hand rather
than being deleted outright. Still open from this list: the import-size
warning, the coarse separation progress bar, the render screen, and
presets — those stay in the present tense because they still are.

- **Nothing in the interface played audio, and nothing said so — closed by
  Plan 3b's mixer.** This was the gap that actually bit during testing:
  `Page.Song` announced "separated" with four stem names and then offered no
  next action — no preview, no render, no player. `POST /api/preview` already
  returned WAV bytes in well under a second once a session was warm, and
  `POST /api/renders` already produced a file, but no view called either
  endpoint, so a reasonable person separated a song, found no way to hear
  anything, and concluded the tool was broken. Plan 3b's mixer
  (`Page/Mixer.elm`, `ui/ports/audio.js`) closes it: opening a separated song
  now offers a scrubber that plays, with soloing and every decay control
  reachable from the same screen. The reasoning worth keeping is the standard
  this gap set for the time in between — announcing success while offering
  nothing is worse than announcing nothing — which is why Plan 3a's own song
  view, while this was still open, said plainly that preview and render would
  arrive later rather than staying quiet about the missing capability.

- **Orphaned `running` rows used to survive a server restart — closed by Plan
  3b's Task 1.** `separation_status` is set to `running` before a job starts,
  and was cleared only by a terminal status or one of `separate_song`'s two
  exception handlers; process death bypassed both, so killing or suspending
  the server mid-separation left the song claiming to separate forever, with
  no job behind it — the in-memory `JobManager` had died with the process.
  Observed in practice: two rows stranded at `running` after a `Ctrl-Z`, which
  suspends rather than kills and looked identical to having exited. Plan 2b
  had already fixed this class of bug for exceptions; process death was the
  case that was missed, and the fix was exactly as small as it looked:
  `Store.reconcile_orphaned_separations()`, called from `lifespan` immediately
  after the store opens (before the job manager or session registry exist),
  resets every `running` row to `pending` at boot, since **any `running` row
  at that moment is definitionally orphaned** — the job manager is in-memory
  and nothing else could still be tracking it. See `docs/architecture.md`'s
  server section for where this sits.

- **No warning about how long a large import would take, and no way to stop
  a separation once it had started — both closed by Plan 3c.** A 70-minute
  file used to import instantly and then queue a separation that ran for a
  very long time and held several gigabytes — measured at 6.2 GB resident for
  one such job — with nothing to do about it but kill the server by hand,
  because the only worker in the process was already inside a single opaque
  `demucs.apply_model` call nothing could interrupt. That is the incident Plan
  3c exists to close, and it closes all three parts of it: `Warn.forSource`
  names the file's length and the single-worker constraint before either the
  Separate or Render button is pressed, once source audio passes fifteen
  minutes; `separation_process.py` moves Demucs into a killable subprocess, so
  a separation started by accident can now be cancelled and the song comes
  back to `pending` with nothing left in the cache; and the queue screen
  (below) makes the wait itself visible instead of a silent hang.

  **The queue depth half of this is closed** by Plan 3c's queue screen:
  `Page.Queue` renders `GET /api/jobs` as what is running, what is waiting
  behind it and what recently ended, with a Cancel button on everything still
  stoppable — reached from the library's nav strip. That is the escape hatch
  the operator previously had to use `kill` for. What is still missing is an
  *estimate*: the screen can say a job is 15% done, but nothing anywhere
  predicts how long a separation will take from the file's duration, so
  `Warn.forSource`'s fifteen-minute line is a judgement call rather than a
  derived number — and, per the render-timing measurement in the Plan 3c
  section above, it is a warning that watches source length while a render's
  own cost is dominated by the configured output length instead.

  Note also what the queue screen structurally cannot show: `JobManager` holds
  its jobs in memory and keeps fifty terminal ones, so the screen is empty
  after every server restart and forgets old finished work. It says so on the
  screen rather than looking broken.

- **No loop region on the waveform, and no route that could draw one — closed
  by Plan 3b's Task 2.** The spec's Song view asked for the detected loop
  region marked plus a tempo readout, and Plan 3a's goal line had promised
  "see its waveform and detected loop" — but nothing in that plan could have
  delivered it, because no endpoint exposed a detected loop or a tempo:
  `server/api/songs.py` had import, list, get, peaks and separate, and nothing
  else; `analysis.find_loop` and `_estimate_tempo` were reachable only from
  inside a render or a `RenderSession`, never over HTTP. `Waveform.loopRegion`
  had been written anyway and was dead code on that branch: `Page/Song.elm`
  passed `loop = Nothing` and had nothing else it could pass.
  `GET /api/songs/{id}/loop` (added in this plan's Task 2, documented in
  `docs/architecture.md`'s server section) closes it: it calls `find_loop`
  directly against the whole file, needing no separated stems and no warm
  session, so it answers before separation has even happened — and both
  `Page.Song` and the mixer now fetch it and pass a real region through. The
  reasoning worth keeping: the plan's goal line was corrected before this
  closed (see the note at the top of
  `docs/superpowers/plans/2026-08-04-elm-shell.md`) precisely because
  promising a feature with no route behind it is worse than not promising it,
  and this entry is the record of why that route had to exist before the Elm
  half could be built — a caution worth keeping for whatever the next
  endpoint-shaped gap turns out to be. **The route itself still has no cache**
  and re-runs beat tracking on every call, which the mixer now calls more
  often than anything before it did; that remains open and is recorded
  separately above, under Plan 3b.

- **The separation progress bar is real but has almost nothing to animate.**
  The SSE machinery works end to end — `watchJob` opens the stream, events
  decode, `Watching`'s fraction reaches the bar. What is thin is the payload.
  Plan 3c's subprocess split changed the numbers without changing the
  substance: the job emits `0.0` from the route's own `reporter.emit`, then the
  worker's three hard-coded phase lines (`separation_worker._phase`: `0.05`
  "Loading the model", `0.15` "Separating stems", `0.90` "Writing stems"), then
  `1.0`, which is terminal and clears the bar. **The whole Demucs run happens
  between `0.15` and `0.90`**, so the bar jumps to 15% within a second or two
  and then sits there for the entire separation — the several minutes that are
  the only part anybody is waiting through. It reads "15%" the whole time.

  It is not that Demucs cannot report more: `demucs.apply.apply_model` takes a
  `progress` flag, and `_demucs_separate` passes `progress=False`. Turning it
  on writes a tqdm bar to *stderr*, which `_StderrTail` drains and keeps only
  as a failure tail — so making the bar move means parsing that, or splitting
  the call per model shift and emitting a phase line between each, and neither
  is a line of work.

  **Anything inheriting this bar should not assume it moves.** A render does —
  `pipeline.run_pipeline` reports many intermediate fractions through its stage
  checkpoints, see `docs/architecture.md` — but a separation's does not, and a
  screen that says otherwise is telling the operator a bar is informative while
  they decide whether to cancel. `Page.Queue.progress` said exactly that until
  Plan 3c's final fix wave, and now says what is true.

- **No mixer — closed by Plan 3b's Task 6.** Nothing in this UI read
  `/api/schema` or let a user touch a single decay/reverb/tempo parameter;
  separation was the only action a song screen offered. `Page/Mixer.elm` is
  the mixer now.
- **No preview playback — closed alongside the mixer.** `POST /api/preview`
  existed and was tested on the server side, but nothing in this frontend
  called it, and there was no `ports/audio.js` — no `decodeAudioData`, no
  looped playback, no buffer swap at a loop boundary. All of that exists now;
  see `docs/architecture.md`'s frontend section for the gapless-swap and
  coalescing design.
- **No schema-driven controls — closed alongside the mixer.**
  `config.config_schema()` — bounds, labels, and help text for every
  `MixConfig` field — was not consumed anywhere in `ui/`. `Schema.elm` and
  `Config.elm` consume it now, and generate the mixer's controls from it.
- **No render screen — closed by Plan 3c.** Starting, watching, cancelling, or
  downloading a full render (`server/api/renders.py`, all built in Plan 2b)
  had no frontend at all. `Page/Renders.elm` is that screen now; see the Plan
  3c section above for what it does and the pairing bug its own review found
  and fixed.
- **No presets — closed by Plan 3d.** `server/api/presets.py`'s CRUD had no
  corresponding screen; `ui/src/Page/Mixer.elm`'s preset bar is that screen
  now, and `PUT /api/presets/{id}` (added the same plan) is what lets one be
  renamed or saved over rather than only ever created fresh. See the Plan 3d
  section above. Per-song config memory — remembering, and re-applying, a
  preset for a specific song — was considered in the same plan and rejected
  rather than built; that section explains why.

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
time-stretch) was measured at **117 s cold versus 73 ms warm** against a
2:43 test file. Plan 3b's own Task 7 repeated the measurement against a
different, 4:06 file with the separation cache freshly cleared and got
**180.55 s cold, 97–340 ms warm** — consistent with the older figure once the
~1.5× difference in track length is accounted for, not a contradiction of it;
see `docs/architecture.md` for the full breakdown of what each number
includes. Every request
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
(`feat/elm-shell`) items found during this plan's review, followed by Plan 3f
(`feat/legibility`) items found during this plan's own final task, which is
also where two long-false entries above (the renders resource problem, the
`JobManager` leak) were finally retired and a third (the `shutil` import) was
found alongside them.

- **Four things contribute to a render's final peak that `master_gain`'s
  calibration window never sees.** `preview.master_gain` measures one window,
  `render_window(session, 0.0, reverb=<the flag>, master=False)`, and derives
  a gain from its peak. `pipeline.run_pipeline` peak-normalizes something
  rather different, and each difference moves a preview off the render's
  level. Listed by measured magnitude, largest first, with a caveat the first
  entry itself is now the record of: the largest number here had the wrong
  story attached to it for a whole branch, corrected only once someone
  measured directly instead of inferring. All four were measured the same
  way: RMS of a mid-arc mastered preview over the corresponding crossfade-free
  region of a real `run_pipeline` output, default config, changing one thing
  at a time. The baseline — default reverb, `reverb=True`, fades off — is
  **1.0003, +0.00 dB**, and is what `tests/test_preview.py`'s
  `test_a_mastered_preview_sits_at_the_render_s_level` now asserts.

  1. **The 1.82 dB attributed to fade ordering does not describe the mixer's
     actual default render, and the transient-at-t=0 hypothesis that replaced
     it as a first guess doesn't either — but the figure itself turned out to
     be exactly reproducible, and content-dependence is the reason both of
     those things are true at once.** The figure — **0.8107, −1.82 dB** —
     is real, traced this task to its literal source, and stays recorded.

     **Where the number actually comes from.** `tests/test_preview.py`'s
     `_level_cfg()` builds a `MixConfig` with `output.duration_min = 0.5`
     (a 30-second render, for a fast, well-posed test) and both fades
     zeroed; its own docstring already said "at the default 8 s fade-in the
     same measurement reads −1.82 dB" — this task confirmed it rather than
     taking the docstring's word for it. Re-running
     `_preview_to_render_ratio` (the RMS-of-mid-arc-window method the
     baseline above uses) against `_level_cfg()`'s synthetic stems
     (`conftest.fake_separate`: three summed sine tones, not a real
     recording) reproduced both figures this document already carried,
     essentially exactly: fades zeroed gives **1.0003181, +0.0028 dB**
     (matching the recorded baseline "1.0003, +0.00 dB"), and setting fades
     to the real `MixConfig` defaults (8 s in / 12 s out) gives
     **0.8107466, −1.8223 dB** (matching the recorded "0.8107, −1.82 dB" to
     four figures). **The number is exactly right for the config it was
     measured in.** That config is a 30-second render — where an 8 s fade-in
     plus a 12 s fade-out cover 20 of the render's 30 total seconds, two
     thirds of the whole arc, not the 0.67% of a 20-minute arc the original
     entry's own arithmetic (correctly) assumed. The entry conflated "this
     number is real" with "this number describes the mixer's actual default
     render" — only the first is true.

     **What the mixer's actual default does, measured directly rather than
     re-inferred (Task 6 of this plan):** a render at the real default
     config (`duration_min = 20`) against a throwaway `SLEEPMIX_DATA_DIR`,
     stems supplied via `sleepmix.separation._write_cache` from this
     repository's own orphaned separation cache
     (`.sleepmix_cache/004542e5a96e70ee/`, a real 2:43 track — the same one
     Plan 2b's cold-session-build measurement above uses, and **not** the
     4:06/246.6 s track Plan 3b's Task 7 and Plan 3c's render-timing figure
     use; the two are different source files and a reader comparing numbers
     across this document should not assume otherwise), reporting on the mix
     immediately before `_apply_fades`. **The global peak is not at t = 0.**
     It sits at t = 14.657 s of a 1200 s render (sample 646,351 at 44.1 kHz)
     — roughly one loop-length (11.0 s) past the start, comfortably outside
     both the 8-second fade-in and the last-12-second fade-out. It is
     **7.12 dB** above the 99th percentile of |sample| across the whole
     render (1.358 vs. 0.598), so it is a real, audible peak rather than a
     lone outlier in the noise floor. It is **40 samples (0.91 ms) wide** at
     half its own height, and the raw samples across that width rise and
     fall smoothly — not a one- or two-sample discontinuity — which reads
     as a genuine moment in the music (most plausibly the `bass` stem, the
     most energetic of the three stems enabled by default with `drums` off)
     rather than a decoder or splice artefact. It survives
     `cycle_crossfade_ms = 0` bit-for-bit — identical sample index,
     identical value to the last digit — which rules out the inter-iteration
     crossfade (item 2, below) as its cause. And directly comparing the
     pipeline's own `normalize_peak` gain factor with fades at their default
     8 s/12 s against the same fades zeroed, at this exact config, gives the
     identical factor either way — **0.6564188599586487, both times, to the
     last digit.** Separately, `preview.master_gain(session, reverb=True)`
     for this render is 0.6564188545205888 — equal to that same factor to
     eight significant figures, a **0.00 dB** gap, not 1.82, measured by
     direct comparison of the two gain factors rather than by the RMS method
     above. Repeating that same direct gain-factor comparison at
     `duration_min = 0.5` — matching the short-render *length* the 1.82 dB
     figure was measured at, but with these same real stems instead of
     synthetic sine tones — again gives an identical factor with fades on or
     off. **So the arc length is not what makes the difference; the content
     is.**

     **The mechanism, and why both are true at once.** A monotonically
     decaying pure tone (`_level_cfg()`'s synthetic stems: no dynamics, no
     transients, decay applied on top of a constant sine) has its own
     un-faded peak guaranteed to sit at t = 0, because nothing else in the
     signal can ever exceed it. Fading that region — worth two thirds of the
     arc at `duration_min = 0.5` — measurably lowers the peak `normalize_peak`
     finds, raising the gain applied to everything else, exactly as the
     original entry described: this is not a wrong explanation, it is a
     correct one for the signal it was measured against. A real 2:43
     recording has no such guarantee — its loudest moment is wherever the
     music happens to be loudest, and at this stem set that turns out to be
     3.65 s into the render's second pass through the loop, nowhere near
     either fade, at both output lengths tested. `master_gain`'s own
     docstring assumption — "decay only removes energy, so the peak falls
     monotonically across the arc and iteration 0 is the loudest window this
     module can produce" — is true of the synthetic signal it is usually
     verified against and not reliably true of real material, where decay is
     negligible this early in the arc and which of the first several
     iterations is loudest tracks the music, not iteration order.

     Both explanations this document has carried for the 1.82 dB are
     therefore not simply wrong: the transient-at-t=0 guess is wrong outright
     (Step 1 found a real transient, just not at t=0, and not affected by
     the fade); the original fade-ordering story is *correct*, reproduced
     exactly, for the synthetic short-duration fixture that produced the
     number, and does not generalize to what the mixer's real default does
     with a real recording, where the same measurement — at either the
     fixture's 30-second length or the mixer's real 20-minute one — reads
     0.00 dB. The live, evidenced explanation for the gap between the
     recorded figure and the mixer's real behavior is content-dependence:
     whether the calibration and normalization windows agree depends on
     whether the material's own loudest moment sits where a fade (or,
     failing that, nothing at all) can move it — true by construction for a
     decaying pure tone, and, on the one real track measured here, false at
     every duration tried. **Why this is not being closed regardless of
     which regime a given render falls into:** `preview.render_window`
     applies one gain factor to every window, computed once per `reverb`
     setting and memoized on the session (`sleepmix/preview.py:101`), so the
     ratio between a preview at the start of the arc, the middle and the end
     is exact whatever the true offset between `master_gain` and
     `normalize_peak` turns out to be for a given song. A uniform offset
     cannot change any comparison the mixer exists to support. See Plan 3e's
     retirement, in the Plan 3f section below, for the fuller reasoning.
  2. **The inter-iteration `equal_power_crossfade` can sum above a single
     iteration's peak.** Two consecutive decayed iterations overlap for
     `cycle_crossfade_ms`, and their sum in that region can exceed either
     one alone, so `normalize_peak` pulls the whole render slightly further
     down than a one-window calibration predicts. Measured on the dry path
     (`reverb.wet = 0.0`, `reverb=False`): **1.0431, +0.37 dB**, which drops
     to 0.9995 with `cycle_crossfade_ms = 0.0` and nothing else changed —
     so the residual is entirely this. With default reverb it is masked to
     about 0.01 dB, because reverb smears the peak either way. Still open.
  3. **A preview and a render can disagree by about 0.01 dB with default
     reverb on, and the reason is the calibration window, not the memo that
     caches its result.** Still open. This entry has been closed once and
     reopened, and the round trip is the part worth keeping.

     **What was closed, and why it was reopened.** The entry used to read
     "`output.sample_rate` is absent from `RenderSession._master_key`,
     although `run_pipeline` resamples before normalizing" — and Task 5 of
     Plan 3f added it (commit `1500e39`), with a review that traced the
     invalidation chain end to end and found every link sound: a changed
     rate gives a different key, the comparison in `update_config` fails,
     `master_gain.clear()` runs. Every link was true. **Nobody measured the
     value at the far end of the chain.** The final review did, and it is
     bit-identical:

     ```
     sample_rate=22050   wet=0.5556662371509203
     sample_rate=44100   wet=0.5556662371509203
     sample_rate=48000   wet=0.5556662371509203
     peak_db=-6  (control)   wet=0.31247408816298333
     channels=1  (control)   wet=0.5853150780716774
     ```

     Reproduced independently during the fix wave against a different
     synthetic song (different absolute figures, same invariance: all three
     rates identical to the last digit, both controls moving). The reason is
     one line: **`preview.render_window` never resamples.** It works end to
     end at `loop.sr`, and `output.sample_rate` is read in exactly one place
     in the whole codebase — `sleepmix/pipeline.py:81`, the resample before
     normalizing — which every preview path has already finished before. So
     adding `sample_rate` to `_master_key` *cannot* change the value
     `_master_key` guards. What it can do is make the operator pay a full
     extra calibration window on a rate change, which is precisely the cost
     `_master_key`'s own docstring exists to prevent. Task 5's change and
     its test were reverted in the final fix wave; the docstring now records
     the measurement so the field is not re-added on the same reasoning.

     **What is actually still open** is the residual this list's baseline
     leaves behind: with default reverb the preview-versus-render offset
     measures about **0.01 dB** (see item 2 — the crossfade's +0.37 dB on
     the dry path is masked to roughly that with reverb on). That is a
     *calibration-window* gap — the window `master_gain` measures is not
     quite the signal `normalize_peak` sees — and no change to the memo's
     key can move it. Closing it means changing what the window contains,
     which is items 1, 2 and 4 in this list, not this one.

     **The three other absences from `_master_key` are not bugs, and this
     entry previously said they were.** `fade_in_s`/`fade_out_s`,
     `cycle_crossfade_ms` and `config.soundbed` are all absent from the key,
     and Plan 3f's Task 5 recorded that as a second real defect — that even
     with a perfect calibration window, a session would keep serving a stale
     gain after the operator moved the fade-in slider. **Measured, it does
     not.** `render_window` at progress 0.0 gets `iteration = 0` and takes
     the empty-context branch (`sleepmix/preview.py:196-199`), so it never
     reaches the crossfade, the fades or the bed at all; the gain is
     bit-identical with `cycle_crossfade_ms = 0`, with both fades zeroed,
     with `soundbed.enabled = True`, and with `duration_min = 40`. **The
     memo is sound as written and these four fields must not be added to
     `_master_key`** — doing so would buy nothing and cost a calibration
     window each, which is how item 3 got closed wrongly the first time.
     The calibration-window gaps those same fields *do* cause are items 1, 2
     and 4; that they name the same fields is a coincidence of which stage
     the window skips, not evidence of a second bug.
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
     `False` in any case. Still open — see also the sound bed's absence from
     *previews entirely*, a different and larger problem, recorded in the
     Plan 3f section below.

  All four are still open, deliberately — see Plan 3e's retirement below for
  why closing them was judged not to serve the mixer's actual job. Item 3 was
  briefly marked closed by Task 5 of this plan and reopened by the same plan's
  final review, on a measurement; the entry itself records the round trip,
  because "the invalidation chain is sound" was true and beside the point.
  They were recorded in the first place because the sizes were
  counter-intuitive — the one written down first was the smallest, and the
  largest had never been measured against the mixer's actual default until
  this task did it, and found the number it already had on file described a
  test fixture rather than the mixer.

- **Nothing is ever reclaimed, and the one that mattered most is now closed
  halfway.** Ranked by how much it actually costs. Both of the first two were
  found false, as recorded — closed by the same commit, `feat/render-queue`
  (Plan 3c), never retired from this document until now.

  ~~Render output files accumulate forever. There is no `DELETE
  /api/renders/{id}`, no pruning, no size cap and no retention policy.~~
  **Half closed, by Plan 3c.** `DELETE /api/renders/{render_id}`
  (`sleepmix/server/api/renders.py:125`, commit `16125cc`, `feat: honour
  cancel before a job starts, bound job retention, delete renders`) exists
  now — refused with a 409 while the render is still queued or running, and
  otherwise removing both the database row and the file on disk; it is what
  the render screen's Delete button calls. What the entry actually named as
  the resource problem is still true, though, and this document should not be
  read as having closed it: there is still no *automatic* pruning, no size
  cap, and no retention policy, so a project that never visits the render
  screen to clean up after itself still accumulates the same roughly **300 MB
  per render** (default 20-minute duration, 44.1 kHz stereo float32) it always
  did. What changed is "no way to reclaim the space at all" becoming
  "reclaiming it is a manual, per-render click" — a real improvement, not the
  same thing as the original problem being solved.

  ~~`JobManager._jobs`, `_tokens` and `_subscribers` are never evicted.~~
  **Closed, by Plan 3c.** `JobManager(..., keep_terminal=50)`
  (`sleepmix/server/jobs.py:63`) and `_evict` (`:220`), called from `_update`
  whenever a job reaches a terminal status, drop the oldest terminal jobs
  from all three dicts once more than `keep_terminal` have accumulated, and
  never drop a queued or running one regardless of how many there are — kept
  as history rather than deleted because the leak this entry described was
  real when written, and the reasoning for why live jobs are exempt (the
  queue screen's whole purpose is to say what is about to happen) is worth a
  maintainer having on hand.

  **`SessionRegistry._use_locks` is only cleared in `clear()`.** Still true,
  still open — nothing in Plan 3c or any later plan touched
  `server/sessions.py`'s eviction. One `RLock` per song id ever previewed,
  deliberately kept past eviction so a thread holding one cannot have it
  swapped out from under it. A few dozen bytes each, bounded by distinct
  songs previewed in a process — the smallest of the three, and noted only so
  it is not mistaken for an oversight.

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

- ~~`separation.invalidate_cache` imports `shutil` inside the function, while
  the module imports `os` and `hashlib` at the top.~~ **Closed by Plan 3c, as
  a side effect rather than a deliberate fix.** `fix: publish the stem cache
  atomically` (commit `f87632b`) moved `import shutil` to the top of
  `sleepmix/separation.py`, alongside `hashlib`, `os`, `tempfile` and
  `warnings`, because the new atomic `_write_cache` needed `shutil.rmtree` at
  module scope for its staging-directory sweep and its rename-then-remove
  dance — the local import inside `invalidate_cache` became redundant in the
  same commit and is gone. Nobody was checking this document against that
  diff at the time, which is exactly the kind of drift this pass exists to
  catch.

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

- **`MixConfig.separation_model` carries no field metadata.** Every
  other config field has a `label`/`help`/bounds dict for `config_schema()`
  to read; this one falls through to an auto-generated label
  (`"Separation model"`) and no help text, because it sits
  directly on `MixConfig` rather than in one of the nested per-section
  dataclasses `config_schema()` was designed around. (`seed` sat there too
  until Plan 3b gave it `label`, `min: 0`, `step` and `help` — see the entry
  above on bounds being the schema's job. Giving `separation_model` a
  `choices` list is the obvious next move and is parked with the rest of the
  separation-model question.)

- **`MixConfig`'s validation layer covers one field.** `MixConfig.validate()`
  (called from `MixConfig.from_dict`, which every config-accepting endpoint —
  presets, preview, renders — routes through) rejects a negative `seed`, and
  that is the only thing it checks. `config_schema()` publishes bounds
  (`min`/`max`/`step`/`choices`) for every other field, but nothing enforces
  them — they remain advisory metadata for a UI to build controls from. A
  config posted with `tempo.speed: 50` is still accepted and rendered.

- **The cache write is a single atomic rename now, superseding a two-step
  ordering this document used to describe as current.** `separation._write_cache`
  builds the fallback marker (if any) and every stem into a sibling staging
  directory and renames the whole thing into place in one step
  (`docs/architecture.md` has the full mechanism and why Plan 3c's killable
  separation is what forced it). An interrupted write, from any cause, now
  leaves either the complete previous cache or no cache at all — never a
  marker with no stems, and never stems with no marker.

  **The old two-step version, and the reasoning that justified its ordering,
  is worth keeping as history rather than deleting outright.** Before this,
  `_save_fallback_reason` wrote the marker and a separate `_save_cache` wrote
  the stems, in that order, directly into the final cache directory, on
  purpose: a failure between the two steps left a stale marker with no stems
  (which `_load_cache` — requiring at least one `.wav` file to report a hit —
  correctly read as a miss and recomputed) rather than stems with an
  unrecorded fallback, which would have read as a properly separated song
  that happened to have one stem. `_load_cache`'s cache-hit check does not
  save a caller from that branch, because it fires *before* the branch is
  ever reached, on the *next* call — an earlier version of this document
  claimed otherwise and was wrong to. If the marker survived and a later
  recompute succeeded without a fallback, `_save_fallback_reason` was called
  with `reason=None` and removed the stale marker it found still sitting
  there — the one route to that branch that mattered, and the reason it was
  kept rather than deleted despite looking like dead code.
  `tests/test_separation.py::test_a_marker_without_stems_does_not_masquerade_as_success`
  still exercises the same shape of failure — a write that does not complete
  must not be trusted on the next call — against the current atomic
  `_write_cache`, by forcing it to raise outright; the two-step ordering it
  used to exercise no longer exists to test.

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

**Plan 3f (`feat/legibility`) items, found during this plan's own final task.**
Every entry above this point was checked against the code it describes as
part of this pass; the two marked closed above (the render-file/JobManager
resource entry and the `shutil` import) were found false and retired here.
What follows is new — found while making that check, not a correction of an
existing claim.

- **Plan 3e (level-matching) was retired before implementation, and the gap
  in plan numbering between 3d and this one is not a mistake.**
  `docs/superpowers/specs/2026-08-05-level-matching-design.md` records why. It
  was going to fix the fade-ordering entry above by reordering
  `pipeline.py`'s normalize-then-fade steps, on the strength of the same
  attribution this task's own measurement has since shown does not hold. The
  retirement reasoning does not depend on which explanation is right, though,
  which is why it survives that correction: `preview.render_window` "applies
  one gain factor to every window… computed once per `reverb` setting via
  `master_gain` and memoized" (`sleepmix/preview.py:101`), so the ratio
  between a preview at the start of the arc, the middle and the end is exact
  regardless of what the true offset between `master_gain` and
  `normalize_peak` is. A uniform offset cannot change any comparison the mixer
  exists to support — the judgement a preview exists for is "how eroded is
  this by the middle," not "does this match a render's absolute loudness
  played back tomorrow on a different device." One small piece survived into
  this plan instead of the level-matching rewrite: correcting the 1.82 dB
  entry above. A second, giving `output.sample_rate` to `_master_key`
  (Task 5), was reverted by this plan's final review once the memoized gain
  was measured at three output rates and found identical — see item 3 above.

- **The sound bed's absence from previews is a character gap, not a level
  one, and it is still open.** `render_window` sums only the configured
  stems and never calls `soundbed.build_soundbed`, so turning on binaural
  beats or pink noise changes nothing audible in the mixer — unlike the four
  calibration-window items above, which are all inaudible-by-design offsets
  in level, this one changes what the judgement previews exist to support
  actually hears: it touches character, not loudness. It is currently handled
  by disclosure alone, and disclosure got more careful during this branch
  rather than less: `sectionNote` used to carry a line about this under
  "Output," until commit `e6357cf` (`fix: two things the mixer said twice,
  and one it contradicted`) deleted it rather than let it repeat what
  `SoundbedConfig`'s own server-sent description now says immediately above
  the section — see the comment at the `"output"` case of `sectionNote` in
  `ui/src/Page/Mixer.elm`. Checked this task, as asked: the two do not
  duplicate each other on screen. The section description says the bed is
  mixed in at render time and never appears in a preview; nothing else on the
  section repeats that sentence. Whether disclosure is enough, versus
  actually mixing the bed into `render_window`, is left unrevisited on
  purpose — that is an audio change with its own design, not a documentation
  one, and this task writes no application code.

- **Help lines are siblings of their controls, not attached to them for a
  screen reader.** `Page.Mixer.helpLine` renders `p [ class "field-help" ]`
  (`ui/src/Page/Mixer.elm:1677`) as a sibling of the control it explains, with
  no `aria-describedby` on the control pointing at it — a screen reader
  announces the control and its label on focus and says nothing about the
  help text sitting right below it on screen. Larger than it looks, because
  the same gap exists one level up: every field label is `span [ class
  "field-label" ]` (four call sites in `ui/src/Page/Mixer.elm`), never
  `<label for=…>`, so there is no accessible name/description association to
  hang `aria-describedby` off in the first place without also giving every
  control a real `id` and every label a `for`. Not fixed here — this task
  writes no application code — but worth flagging now, since the help text
  this plan added across five tasks is exactly the content that needs the
  association to reach anyone using a screen reader.

- **The top-level description's missing-key fallback has no test.**
  `ui/tests/SchemaTest.elm`'s `"a section without a description decodes to
  \"\" rather than failing"` test, added alongside the schema's description
  decoding earlier in this plan, exercises `decodeSection` only — the
  section-level decoder. Nothing decodes a top-level `/api/schema` response
  with no `"description"` key at all and asserts `schema.description == ""`;
  `Page.Mixer`'s own `sectionDescription` tests (`ui/tests/MixerTest.elm`)
  construct the `Schema.Schema` value directly with `description = ""` rather
  than decoding JSON that omits the key, so they exercise the fallback's
  *use*, not its *decode*. Same pattern, same low risk as the section-level
  version it sits beside — recorded so the asymmetry isn't mistaken for the
  top-level case being untested by design.
