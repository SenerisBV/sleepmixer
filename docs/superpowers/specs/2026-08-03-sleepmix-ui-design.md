# sleepmix UI — design

**Date:** 2026-08-03
**Status:** approved, not yet implemented
**Scope:** local web UI plus the core hooks it needs. Segment selection and
arrangement are explicitly out (see [Future work](#future-work)).

## Why

sleepmix works. A 25-minute disintegrating mix renders correctly from the CLI,
and the DSP core is fast — a 30-second render completes in 1.9 s once caches are
warm. What it lacks is a way to *hear what a parameter does* without committing
to a full render. Tuning a decay curve currently means editing YAML, rendering
25 minutes, listening, and going back. That loop is slow enough that the most
interesting part of the tool — per-stem erosion, the thing you can't do to a
finished master — is the part that gets tuned least.

The goal is to make that loop immediate, and to make the tool usable by someone
who can follow install instructions but should not have to edit YAML.

## Audience and distribution

A **local** tool, run by the operator and distributed to semi-technical people:
`pip install "sleepmix[all]"`, then `sleepmix ui`. Not hosted, not multi-user,
no authentication.

An early version of this design treated packaging as a major subsystem. That was
wrong, and the correction is recorded here so it is not re-litigated:

- **PyTorch is not a distribution problem.** 443 MB installed, pure pip wheel,
  no system dependencies, no compiler.
- **Demucs weights self-manage.** `get_model` downloads them on first use into
  `~/.cache/torch/hub` (measured: 321 MB across four `htdemucs_ft` checkpoints).
  No packaging work required.
- **Rubber Band was never in play.** The `rubberband` CLI is not on the
  operator's PATH and never has been. Every render to date, including the
  existing 30-minute `mix.wav`, already went through the librosa phase-vocoder
  fallback at `timestretch.py:24`. It is an optional quality upgrade, not a
  dependency.

So the real install story is one pip command and a ~700 MB download, with zero
system-level prerequisites. A double-click app for someone who never opens a
terminal would be a genuine project — bundled runtime, ~1.5 GB installer, macOS
code signing — and is out of scope.

## Goals

1. Adjust per-stem decay and hear the result immediately.
2. See what a render is doing while it does it.
3. Manage songs, presets, and past renders.
4. Never edit YAML unless you want to.

## Non-goals

- Hosting, accounts, uploads from strangers.
- A DAW. No sample-accurate parameter automation during playback.
- Multi-segment arrangement (deferred; a seam is left for it).
- Bundled-runtime desktop installers.

## The key insight

`apply_decay(loop, progress, decay, rng)` (`disintegration.py:76`) is a pure
function of `progress`. It does not depend on preceding iterations. Therefore
"what does this sound like 70% through the mix" costs **one loop iteration of
compute**, not seventeen minutes of rendering.

Measured on a 6.4 s stereo loop: decay 23–24 ms, reverb 9–34 ms, **~33 ms
total per stem per window**, or ~100 ms for three stems.

This capability already exists in the core. It has simply never been exposed
above the batch pipeline. The interactive preview therefore requires almost no
new DSP — only a new entry point and a memoization layer.

## Architecture

```
ui/                     Elm application (source)
  └── elm make ──► sleepmix/static/app.js     shipped inside the wheel
ui/ports/               hand-written JS: Web Audio engine, SSE bridge
sleepmix/server/        FastAPI: REST + SSE, mounts static, no DSP knowledge
sleepmix/               existing core, unchanged in spirit
  + progress.py  preview.py  session.py  paths.py
```

`sleepmix ui` starts uvicorn on a loopback port and opens a browser tab.

**The server holds no business logic.** It is a transport over the core. This
boundary is what keeps the CLI and the Python API first-class rather than
degraded citizens of the UI, and it is what makes the core independently
testable without spinning up a server.

### Why Elm, and where it stops

The frontend is Elm rather than a JS framework. The reasoning that decided it:

- **The compiler is the verification mechanism.** Much of this UI is written by
  an agent, and Elm converts a whole class of mistakes — wrong field name,
  unhandled case, changed shape — into build failures rather than runtime bugs
  discovered by clicking. Nothing else on the table offers that strength of
  guarantee.
- **Schema-driven forms are *better* statically typed, not worse.** `/api/schema`
  decodes into a closed `Field` union (`FloatField`, `ChoiceField`, `BoolField`,
  …). If the server later grows a control type the UI does not render, the build
  fails. In a dynamically typed frontend that same change silently renders
  nothing.
- **One frozen API.** Elm has had a single stable API since 2019 (0.19.2, July
  2026, changed compiler performance only). There is no version-confusion trap
  of the kind Svelte's stores-vs-runes or React's hooks-vs-RSC split creates.

**Where Elm stops is the important part.** Elm's interop is ports —
asynchronous message passing only, no synchronous FFI, and no binary payloads.
So two subsystems live in hand-written JavaScript and are *outside* the type
system:

| Port module | Owns | Why it cannot be Elm |
|---|---|---|
| `ports/audio.js` | Fetching `/api/preview`, `decodeAudioData`, scheduling playback, swapping the buffer at a loop boundary | Web Audio has no Elm binding; ports cannot carry binary |
| `ports/events.js` | `EventSource` over `/api/jobs/{id}/events`, forwarding parsed events inward | `elm/http` has no SSE support |

**Elm never touches audio bytes.** It sends parameters out (`{stems, progress,
config}`) and receives outcomes back (`{ok, durationMs}` or an error). That
keeps the port surface narrow and JSON-shaped.

This split is worth stating plainly because it inverts the usual expectation:
the compiler protects the forms, routing and library — the parts least likely
to break — while the genuinely bug-prone work, audio scheduling and gapless
buffer swapping, sits in ~250 lines of unchecked JavaScript. That is an
accepted trade, and it means those two modules deserve disproportionate review
attention relative to their size.

**The waveform does not need a port.** Peak pairs render as SVG, and loop-region
drag handles are mouse events mapped to messages — a state machine Elm models
well. Canvas would require escaping Elm's virtual DOM; SVG does not.

**Build and distribution.** `elm make` emits a single `app.js` committed to
`sleepmix/static/`, alongside a hand-written `index.html` and the port modules.
There is no bundler and no `node_modules` for the application itself. Building
requires the `elm` binary; *installing* sleepmix does not. `pip install
sleepmix` continues to need nothing but Python.

### Module responsibilities

| Module | Purpose | Depends on |
|---|---|---|
| `preview.py` | Render one decay-arc window | `session`, `disintegration`, `effects` |
| `session.py` | Memoize expensive per-song intermediates | `separation`, `analysis`, `timestretch` |
| `progress.py` | Structured progress events, cancellation | nothing |
| `paths.py` | Platform app-data and cache locations | nothing |
| `server/jobs.py` | Background render jobs, lifecycle | `progress`, `pipeline` |
| `server/store.py` | SQLite persistence | `paths` |
| `server/api/*` | HTTP surface, one module per resource | everything above |

## Core changes

### 1. `preview.py` — window rendering

```python
render_window(session, progress: float, stems: list[str], seconds: float) -> AudioBuffer
```

Renders one loop iteration at the given point in the decay arc, summed across
the requested (soloed) stems, with reverb applied. Target latency ~100 ms.

**Known fidelity caveat:** reverb is applied per-window, so a preview lacks the
reverb tail bleeding in from the preceding iteration. The window is rendered
with one extra second of leading context which is then trimmed, which recovers
most of it. Previews are representative, not bit-identical to the corresponding
slice of a full render.

### 2. `session.py` — memoized render context

A song's expensive intermediates are stage-cached in memory, keyed by the config
subset each depends on:

| Stage | Invalidated by | Cost |
|---|---|---|
| Separated stems | song file, model | minutes (also disk-cached) |
| Loop point | `LoopConfig` | ~1 s |
| Time-stretched loop | `TempoConfig` | ~1 s |
| Decayed window | `StemDecayConfig`, progress | ~33 ms |

Without this, every preview re-runs the phase vocoder and the preview stops
being interactive. This staging is the difference between 100 ms and 2 s.

### 3. `progress.py` — structured events and cancellation

Replace `Progress = Callable[[str], None]` (`pipeline.py:24`) with a reporter
emitting structured events:

```python
@dataclass
class ProgressEvent:
    stage: str          # separate | loop | stem | soundbed | master
    stem: str | None
    fraction: float     # 0..1 overall
    message: str
```

Plus a `CancelToken` checked between stems and between loop iterations in
`build_disintegrating_stream`.

**The CLI must not regress.** `cli.py` adapts events back to `click.echo`
strings, preserving current terminal output exactly.

### 4. `config.py` — field metadata

Add `field(metadata={"min":…, "max":…, "unit":…, "label":…, "help":…})` to
existing fields and expose it at `GET /api/schema`.

Defaults, YAML loading, and the recursive `_build` (`config.py:138`) are
untouched — `metadata` is inert to dataclass construction. The UI generates its
controls from this rather than hard-coding them, so a new config field appears
in the UI automatically with correct bounds and units.

### 5. `paths.py` — cache relocation

`separation.py:25` defaults `cache_dir` to the CWD-relative `.sleepmix_cache`,
and `pipeline.py:36` never passes it through. Cache location therefore depends
silently on the directory you launched from — which breaks as soon as a server
process runs from somewhere else.

Move to a platform app-data directory, overridable by config, by `--cache-dir`,
and by the `SLEEPMIX_DATA_DIR` environment variable.

### 6. Per-iteration RNG (accepted behavior change)

Currently a single `rng` is threaded through the whole pipeline
(`pipeline.py:33`), so the noise, dropout, and spectral-hole pattern at
iteration *i* depends on every random draw before it. A preview of progress=0.7
therefore **cannot** match what the final render produces at 0.7.

Derive a per-iteration generator from `(seed, stem_name, iteration)` instead.
Preview and final render then agree exactly.

**Consequence, accepted:** renders will not reproduce byte-for-byte against the
existing `mix.wav`. A preview that lies is worse than no preview.

### 7. Optional explicit loop points

`LoopConfig` gains optional `start_s` / `end_s`. Null means auto-detect — current
behavior, unchanged. When set, `find_loop` returns them directly.

Roughly a dozen lines, and it makes the waveform's loop handles draggable. It is
the natural precursor to multi-segment arrangement without committing to any
arrangement model.

## HTTP surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/schema` | Config field metadata for form generation |
| `GET`/`POST` | `/api/songs` | List / import a song |
| `GET` | `/api/songs/{id}/peaks` | Min/max waveform peak pairs |
| `POST` | `/api/songs/{id}/separate` | Trigger separation, returns job |
| `POST` | `/api/preview` | Render a decay window, returns WAV bytes |
| `GET`/`POST`/`DELETE` | `/api/presets` | Named config snapshots |
| `POST` | `/api/renders` | Start a render, returns job id |
| `GET` | `/api/jobs/{id}/events` | SSE progress stream |
| `POST` | `/api/jobs/{id}/cancel` | Cancel |
| `GET` | `/api/renders/{id}/audio` | Download the result |

SSE rather than WebSockets: progress is one-directional, and SSE reconnects on
its own.

Two of these are consumed by the port modules rather than by Elm directly:
`/api/preview` returns binary audio, which ports cannot carry, so `ports/audio.js`
fetches and decodes it; `/api/jobs/{id}/events` is an event stream, which
`elm/http` cannot open, so `ports/events.js` owns the `EventSource` and forwards
parsed events inward. Everything else is ordinary JSON over `elm/http`.

## UI

Four screens.

**Library** — imported songs with separation status; past renders, each storing
the exact config that produced it so any render is reproducible or forkable;
named presets.

**Song view** — waveform with the detected loop region marked, tempo readout,
per-stem availability. The waveform is drawn from **server-computed min/max peak
pairs**, not the audio file; shipping a 40 MB WAV to the browser to decode
client-side would stall the page for no benefit.

**Mixer** — the heart of it. Per-stem rows (enable, gain, reverb send, decay
curve), a global **progress scrubber** representing position in the decay arc,
solo/mute per stem. Dragging the scrubber re-renders that window and plays it
looping. Changing a decay parameter re-renders in ~100 ms and swaps the buffer
at the next loop boundary.

This is **"audition any point instantly," not a DAW.** Parameter changes take
effect at loop boundaries, not sample-accurately during playback. The
distinction is deliberate and should not be papered over in the UI's affordances.

**Render** — duration and output settings, go. Live stage-by-stage progress over
SSE, cancellable. Result lands in the library.

All config controls are generated from `/api/schema`.

## Data

SQLite in the app-data directory, via stdlib `sqlite3` behind a thin
`store.py`. Three tables: `songs`, `presets`, `renders`.

No ORM. The project's existing style is plain dataclasses and light
dependencies, and this schema is small enough that SQLAlchemy would be more
machinery than the problem needs.

Config is stored as **JSON blobs** rather than exploded into columns, because
`MixConfig` already round-trips through dicts (`config.py:127`) and a normalized
schema would need migrating on every new decay parameter.

## Error handling and edge cases

**Silent Demucs fallback.** `separation.py:35` catches every exception and falls
back to a single `mix` stem with only a `warnings.warn`. In a terminal that is
visible; in a UI it is not. The user would configure per-stem decay curves and
receive one undifferentiated stem with no indication why. Separation status
becomes an explicit, surfaced field on the song record, with the failure reason
retained.

**First-run JIT stall.** librosa's numba compilation is cold on first use. During
development the first analysis call exceeded a two-minute timeout while the
second took 0.9 s. A UI that hangs for two minutes on launch reads as broken, so
the server performs a warm-up pass on startup and reports it as an explicit
state.

**Cancellation mid-render.** Partial output is discarded; the job record retains
the cancellation and the config, so it can be restarted.

**Missing source file.** A song row whose file has moved is marked unavailable
rather than erroring the library view.

## Testing

Existing tests cover the DSP core (disintegration, soundbed, looping, config)
and an end-to-end render through the fallbacks. That continues to hold.

New coverage:

- `preview.py` — a **pre-reverb** window at progress *p* is bit-identical to the
  corresponding iteration of a full render. This is the test that enforces
  change 6. It compares before reverb precisely because the post-reverb signal
  is not expected to match (see the fidelity caveat above); a separate test
  asserts the post-reverb window is within tolerance rather than identical.
- `session.py` — invalidation: changing tempo recomputes the stretched loop but
  not separation
- `progress.py` — event ordering, monotonic fraction, cancellation actually stops
- `store.py` — CRUD round-trips, config JSON fidelity
- API — endpoint contracts against a test client

**Database isolation, mandatory.** The test suite gets its own database from the
first store test onward — a pytest fixture points `SLEEPMIX_DATA_DIR` at a
tmpdir, so tests can never touch the real library. This is set up *before* the
first test that touches the store, not retrofitted.

**`pytest` is currently absent** from the pipenv environment (`dev-packages` in
the Pipfile is empty), so the suite is presently unrunnable there. It goes into
`dev-packages` as part of this work.

## Documentation

A `docs/` tree with architecture notes and a project-state document, per
standing preference. The project-state document records anything placeholder or
deliberately deferred.

## Future work

Deliberately out of scope, recorded so the seams are intentional:

**Segment selection and arrangement.** The current model is one auto-found loop,
repeated to fill the duration, decaying monotonically 0→1. Choosing *which*
segments get used means multiple sources arranged on a timeline, which breaks
that single-loop assumption in `pipeline.py:78-86` and `disintegration.py:114`.
The seams left for it: optional explicit loop points (change 7), schema-generated
config UI, and an Elm frontend where a timeline is a new `Msg` variant and a new
view function rather than a migration. Elm helps here specifically: adding
segments changes the shape of the config, and the compiler will enumerate every
place that must be updated rather than leaving them to be found by clicking.

**Output length editing** — trivial in config terms, but interesting once
segments exist, because "length" stops being a single number and becomes an
arrangement property.

**Bundled desktop app** — only if the audience shifts from semi-technical to
non-technical.
