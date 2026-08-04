# Plan 3c: jobs you can watch and stop

**Status:** design approved 2026-08-04, not yet planned.

## What this is for

`sleepmix` takes one song, separates it into stems, finds a loop, and repeats
that loop for half an hour while eroding it. Plan 3a gave it a library and a
song screen; Plan 3b gave it a mixer you can hear while you set it up. What it
still cannot do is produce the thing the whole tool exists to produce — a
finished mix — from anywhere except the command line.

The server side is already almost entirely built. `POST /api/renders` starts a
render, `GET /api/renders` lists them, `GET /api/renders/{id}/audio` serves the
file, `POST /api/jobs/{id}/cancel` cancels, and `GET /api/jobs/{id}/events` is
the SSE stream the separation panel already consumes. What is missing is the
interface, and one genuine capability: **the ability to stop a separation that
has already started.**

## The problem that motivated this plan

During Plan 3b's own testing the operator imported a very large file by
accident, started separating it, and then wanted to test a smaller one. There
was no way to get there. `POST /api/jobs/{id}/cancel` returned success, the job
kept running, and in the end the process had to be killed by hand — it turned
out to be suspended rather than dead, holding 6.2 GB.

That is not a UI gap. It is a real limit in how separation runs, and no amount
of frontend work fixes it. A queue screen with a cancel button that silently
does nothing on the one job type that actually blocks you is a screen that
lies.

## Scope, and the split

The four things originally named for "Plan 3c" — render screen, presets UI,
queue visibility, large-import warning — are two coherent projects rather than
one. They share almost no code.

**This plan (3c) is jobs you can watch and stop:** cancellable separation, the
queue screen, the render screen, download and audition, and the long-job
warning.

**Plan 3d is configs that persist:** the presets UI (named recipes reusable
across songs, on the presets table that already exists) and per-song memory, so
reopening a song restores the config you left. Deliberately deferred; Plan 3b
was seven tasks and strained, and each plan should ship working software on its
own.

## Decisions taken during design

**The finished mix is a file first, a playable thing second.** Download is the
deliverable — the operator moves it to another device. Audition exists only to
check the render came out right. This matters because it removes an entire
category of work: no transport controls, no seek bar, no port. A 30-minute WAV
decoded into an `AudioContext` buffer would be roughly 300 MB in memory, which
is the wrong shape entirely; an `<audio controls>` element pointed at the
existing endpoint streams it, costs nothing, and is a plain tag in the Elm view.

**A render starts from the mixer**, because that is where the config lives.
The alternative — starting from the song screen or a renders screen — would
mean rebuilding config selection somewhere it does not belong.

**The queue is live-only.** `JobManager` is in-memory and resets on every
server start. Persisting jobs would mean a jobs table and reconciliation on
startup, which is Plan 3b's `reconcile_orphaned_separations` all over again for
a screen whose whole purpose is "what is happening right now". Renders persist
because they are artefacts; jobs do not because they are events.

## Server work

### Separation moves to a subprocess

New module `sleepmix/separation_worker.py`, invoked as
`python -m sleepmix.separation_worker <input_path> <model> <cache_dir>`. It
performs the separation and writes the stem cache. The parent supervises it:
reads phase lines from stdout and forwards them through the existing
`ProgressReporter`, and on cancel terminates the child and reaps it.

**The existing cache directory is the handoff.** `separate_detailed` already
writes stems to `cache_dir/<key>/<stem>.wav` and reads them back on the next
call, so the child needs no pickling of arrays, no shared memory, and no
serialisation protocol. It writes the cache; the parent calls
`separate_detailed` afterwards and gets a cache hit.

Progress is coarse by necessity. `_demucs_separate` calls
`apply_model(mdl, x[None], progress=False)`, and demucs exposes no callback
there, so the child can report phases — loading the model, separating, writing
— but not a fraction within the separation itself. That is honest and matches
what the UI already does: the separation panel shows an indeterminate bar.

Costs, accepted: torch is re-imported per separation, a few seconds; and macOS
spawn semantics mean the worker must be a real module invoked by path, not a
`multiprocessing` closure.

### The stem cache write becomes atomic

`_save_cache` currently does `os.makedirs(d, exist_ok=True)` and then writes
each stem into it one at a time. `_load_cache` reads whatever `.wav` files it
finds and returns them if there is at least one.

Today nothing can interrupt that write. **Making separation killable makes it
dangerous**: kill the child between the second and third stem and the next run
reads a two-stem cache as a valid four-stem result, and the song plays with
half its content missing and nothing anywhere saying why. This project has
already shipped two silent-failure bugs of exactly this class — an invisible
progress bar and a mixer that played the full default mix when every stem was
switched off — and both took a full branch review to find.

`_save_cache` writes into a sibling temporary directory and `os.replace`s it
into position when every stem is on disk. `_load_cache` needs no change; it
simply stops being able to observe a half-written directory.

### `JobManager._run` checks the token before starting

`_run` currently sets a job to `running` and calls the work function without
consulting the cancel token, so cancelling a job that has not yet reached the
worker does not stop it — it starts anyway and then stops at its first
`cancel.check()`, which for separation is the check that happens *before*
Demucs. The observable effect is a cancelled job that runs to completion.

`_run` checks the token first and, if set, moves the job straight to
`cancelled` without ever calling the work function. This is a live bug
independent of everything else in this plan.

### `Job` gains `created_at`; the manager gains bounded retention

`JobManager._jobs` is a dict that only ever grows — nothing is ever removed for
the life of the process. A queue screen rendering `GET /api/jobs` would show
every job since the server started, forever. **Terminal jobs beyond the most
recent 50 are dropped; running and queued jobs are never dropped**, however
many there are, because dropping one would make the queue lie about what is
about to happen. `created_at` gives the queue a stable order to render, since
dict insertion order is an implementation detail to depend on.

### `DELETE /api/renders/{id}`

Removes the row and the file. A half-hour WAV is roughly 300 MB; without this
the renders screen is a list you can only add to, and the data directory grows
without bound. Deleting a render whose job is still running is refused — cancel
it first.

## Screens

### Renders

Reached from the library. One entry per render: the song it came from, its
status, a summary of the config that produced it, and its length.

- **Done** — a download link, an `<audio controls>` audition, and delete.
- **Running** — the progress bar driven by the existing SSE stream, and cancel.
- **Failed / cancelled** — the reason, and delete.

The config summary matters more than it looks. The renders table stores the
config that produced each file, and a list of six identically-named WAVs is
useless. **It shows the mix length, which stems were enabled, and the decay
endpoint** — the three things that differ between two renders of the same song
in practice. Everything else stays in the stored config, which the row can
expand to show in full.

### The render button, on the mixer

Says what it is about to do before it does it: the mix length from
`output.duration_min`, and whether the stems are already cached — the single
biggest factor in how long it will take.

**It does not fabricate a time estimate.** We have no model of render duration
and inventing one would be worse than saying nothing; a progress bar that lies
about time left is the thing this project has been careful to avoid, in the
same spirit as the deliberately-indeterminate "Preparing…" panel. The plan
measures one real render end to end during its verification task and records
the measured ratio in `docs/architecture.md`; only then, and only if the ratio
turns out to be stable across two tracks, does an estimate become a thing the
interface may claim.

Then it hands over to the renders screen.

### Queue

What is running and what is waiting, in submission order, with the song each
job belongs to and a cancel on every entry. Driven by `GET /api/jobs` plus the
SSE stream already in place.

Because the queue is live-only, the screen says so rather than appearing empty
and inexplicable after a server restart.

### The long-job warning

At Separate and at Render, driven by `duration_s`, which the store already
holds. **Above a threshold — 15 minutes of source audio — it says so before you
commit**, naming the source length and that one worker runs everything, so
anything started behind it waits. It does not block: the operator asked for a
queue they can manage, not a nanny.

The threshold is a judgement, not a measurement. Fifteen minutes is roughly
three times the longest track anyone would normally feed this, and the file
that caused the original incident was seventy. It exists to catch the accident,
not to editorialise about long songs.

## Failure modes the plan must handle explicitly

**A killed child must not leave a partial cache.** Covered by the atomic write;
gets a test that interrupts mid-write and asserts the next read sees the
previous cache or nothing, never a partial one.

**A child that dies for reasons other than cancel must surface as `failed`.**
This is the subtle one. `separate_detailed` wraps `_demucs_separate` in a broad
`except Exception` and falls back to `{"mix": load_audio(input_path)}` — the
whole song as a single stem — with a warning. That fallback is correct for "the
separation extra is not installed". It is badly wrong for "the operator
cancelled" or "the child was killed by the OOM killer", both of which would
silently convert the song to a single-stem mix that then renders and plays
without complaint. The supervisor must distinguish cancellation, abnormal exit,
and genuine unavailability, and only the last may take the fallback path.

**Cancel on a running render is already correct.** `disintegration.py:171-173`
checks the token inside the per-iteration loop, so a render stops within about
a second. Nothing in this plan should disturb that.

## Testing

Subprocess supervision is tested against a **stub worker** — a script that
sleeps and prints phase lines on demand — rather than against real Demucs.
Cancel, phase forwarding, non-zero exit, and interrupted writes all become fast
deterministic tests. One slow test using real separation, marked and skippable,
proves the real worker's contract matches the stub's; without it the stub tests
prove only that the stub works.

The tests must never touch the operator's real data directory. Every test and
every manual verification runs against `SLEEPMIX_DATA_DIR=$(mktemp -d)`; an
implementer on Plan 3a wrote into the real music library before noticing.

## Out of scope

- **Presets and per-song config memory** — Plan 3d.
- **Persisting the job queue across restarts.**
- **Fine-grained separation progress.** Demucs offers no callback at the point
  that matters.
- **Segment selection and arrangement.** The seam is `LoopConfig.start_s` /
  `end_s` plus the loop endpoint, but multi-segment breaks the
  one-loop-repeated model in `pipeline.py` and needs its own design.
- **A path allow-list for `import_song`, streaming peak computation, and
  authentication** — carried forward from Plan 3b's out-of-scope list,
  unchanged.
