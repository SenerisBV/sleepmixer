# ui/

The sleepmix interface, written in [Elm](https://elm-lang.org/). This directory
is the source; it is not what ships. What ships is a compiled JavaScript
bundle, committed elsewhere in the repo — see "The one thing to not forget"
below before you touch anything here.

## What Elm is doing here

Most of this application is written by an agent, and Elm's whole value in
that situation is the compiler: a renamed field, an unhandled union case, a
decoder that no longer matches the server's JSON — each of those is a build
failure here, not something that quietly renders blank and says nothing. The
alternative, a hand-written JS or TypeScript frontend, would let all three
happen silently at runtime, and an agent is exactly the kind of author who
won't reliably notice a blank div where a waveform should be.

`ui/src/Main.elm` is a `port module` built with `Browser.element`. `Model`
carries which screen is showing (derived from `selectedSongId`, not stored
redundantly — see `routeFor`), the state of a library fetch, the song
currently open, its peaks, and any in-flight separation job. `update` is a
plain `Msg -> Model -> ( Model, Cmd Msg )`; every HTTP call sleepmix makes
lives in one file, `ui/src/Request.elm`, so a change to the API surface is a
change to one file and the compiler points at every caller when a signature
moves. `Request.elm` builds its URLs with `Url.Builder` rather than string
concatenation, so ids and query values are percent-encoded; `ports/events.js`
does the same with `encodeURIComponent`.

**A separation is one union, `Separation`, not a pair of fields.** It was
`separating : Bool` beside `trackedJob : Maybe Api.Job`, which could express
"a job is running for this song, but we aren't watching it" — and did, every
time someone left a song mid-separation and came back. The view rendered that
state as a live button reading "Separating…", which queued a second job behind
the first on the server's single worker when clicked. `Idle | Starting
{ request, songId } | Watching Api.Job` makes it unrepresentable: there is no
way to be separating without either a request in flight or a job being
watched. `Starting` carries the request id that will answer it (so a superseded
POST's response is recognised and dropped rather than adopted onto whatever
song is now on screen) and the song it was issued for (so re-entering that same
song keeps the watch instead of orphaning the job). Responses generally are
tagged with a monotonic request id rather than a song id — a song id says "is
this still the song on screen", which a fast A → B → A satisfies for the wrong
reason, letting a stale response overwrite a fresher one.

**Losing the event stream is a state, not a hang.** `ports/events.js` cannot
tell a terminal close from a network blip, a server restart or a 404 for an
unknown job — the browser fires `onerror` for all four — so it reports every
one over a `jobStreamFailed` port and Elm, which knows whether it already saw a
terminal event, decides whether that mattered (`streamFailureFor`). A dedicated
port rather than an error envelope over `jobEvent`, so that channel keeps
carrying exactly one thing decoded by exactly one strict decoder. A malformed
event is handled separately again and says so: separation started fine, the
*event* was unreadable, and both paths end the separation cleanly rather than
leaving the panel at "Separating…" forever.

### Where Elm stops, and why

`elm/http` has no server-sent-events support, so Elm cannot open an
`EventSource` itself. Ports are the only way in or out, and a port is
asynchronous and JSON-only — nothing but a JSON value crosses that boundary in
either direction. `ui/ports/events.js` owns the actual `EventSource`
connection to `/api/jobs/{id}/events`; Elm sends a job id out over the
`watchJob` port and receives parsed job events back over `jobEvent`, decoded
immediately by `Api.job`. Elm never touches audio bytes and never will —
that's the same reason a later addition (Plan 3b's Web Audio playback) is
planned as another hand-written JS port module rather than an Elm package:
decoding and playing audio isn't something ports can carry incrementally, only
handed off to wholesale.

### Strict decoders

`ui/src/Api.elm` is the seam where an untyped HTTP response becomes a typed
Elm value, and every decoder there is deliberately strict. `separationStatus`
and `jobStatus` each read a string status field and `Decode.andThen` into a
closed union; an unrecognised value hits `Decode.fail` rather than falling
through to some default case. A server that starts returning a
`separation_status` this build doesn't know about — a new value added on a
branch that shipped its Python half before its Elm half — fails the decode
loudly (surfaced today as an error string in the relevant panel) instead of
rendering a blank or misleading row. That trade only makes sense because the
frontend and the server it talks to are versioned together in one repo; a
public API talking to clients it doesn't control would need the opposite
default.

## Building it

```bash
cd /Users/moopius/projects/sleepmixer
make ui
```

This runs `elm make src/Main.elm --optimize` from `ui/`, writes the result to
`sleepmix/static/app.js`, copies `ui/ports/events.js` to
`sleepmix/static/events.js`, and records a content hash to
`sleepmix/static/app.js.sha256` via `ui/hash_sources.py`. The hash covers
everything that fed the build — every `.elm` file under `ui/src`,
`ui/elm.json`, and `ui/ports/events.js` — *and* both files that came out of it,
`app.js` and `sleepmix/static/events.js`. The outputs are in there because
hashing inputs alone let two real mistakes through unnoticed: a `make ui-dev`
`--debug` bundle (which changes no input at all, so the recorded hash still
matched) and an edit made to the served copy of `events.js` instead of to
`ui/ports/events.js`.

The target rebuilds every time rather than checking mtimes. `make ui-dev`
writes to the same `app.js`, which then looks newer than every source, so an
mtime-driven `make ui` would have skipped the compile and simply re-recorded
the debug build's hash as current.

### The one thing to not forget

**`sleepmix/static/app.js` is a committed artefact, not a build output the repo
regenerates for you.** `pip install sleepmix` — and `pipx install`, and every
other install path — must not need Node or Elm on the machine running it, so
the compiled bundle has to already be sitting in the package when it's built.
That means: **whenever anything under `ui/` changes, run `make ui` and commit
the resulting `sleepmix/static/app.js`, `sleepmix/static/events.js`, and
`sleepmix/static/app.js.sha256` alongside it.**

The Python test suite catches a forgotten rebuild
(`tests/test_static_bundle.py::test_the_bundle_is_not_stale_relative_to_the_sources`)
by recomputing `ui/hash_sources.py`'s hash and comparing it against the
`.sha256` file committed next to the bundle — but only when that test runs,
which is after the fact. If you're iterating locally and the suite hasn't run
yet, there is nothing else stopping a stale `app.js` from sitting in the repo
looking correct. Note also what the hash does and doesn't prove: it orders
inputs by sorted path, so it's a drift detector, not a reproducibility proof —
renaming a module in a way that changed the sort order while keeping every
byte of content identical wouldn't change the recorded hash.

## Developing it

```bash
cd /Users/moopius/projects/sleepmixer
make ui-dev
```

This is the same `elm make` invocation with `--debug` instead of `--optimize`,
which turns on Elm's time-travelling debugger — the small icon in the
bottom-right corner of the running app that lets you step backward and
forward through every `Msg` the app has received, and inspect `Model` at each
step. It's the fastest way to understand why a screen ended up in some state,
since the whole model is right there rather than scattered across component
state. `make ui-dev` does **not** update `app.js.sha256`, so don't commit a
`--debug` build — run `make ui` again before committing.

There is no dev server with hot reload here; rebuild with `make ui-dev` (or
`make ui`) and reload the browser tab, same as any other change to the
compiled bundle. `sleepmix ui` serves whatever is currently at
`sleepmix/static/app.js`.

## Testing it

```bash
cd /Users/moopius/projects/sleepmixer/ui
elm-test
```

`ui/tests/` has six suites:

- `ApiTest.elm` — the `Api.elm` decoders, including that an unknown status
  fails rather than falling through.
- `JobTest.elm` — the pure decisions in `Main`'s job state machine:
  `jobOutcome` (does this SSE event belong to the job we're tracking),
  `separationOnSelect` (does opening a song keep or discard a running
  separation, and which stream does that leave to close), and
  `streamFailureFor` (is a dead `EventSource` a real loss or the normal
  terminal close).
- `UpdateTest.elm` — the `update` transitions those helpers feed:
  navigating away from and back to a song mid-separation, a terminal event
  arriving while the library is on screen, a stream failure, a decode failure,
  and a superseded separation POST. `Cmd` has no equality in Elm, so these
  assert the model half of `update` and leave the command half to the pure
  helpers above, which is what those helpers were extracted for.
- `SongTest.elm` — `Page.Song.needsForce` across all five `SeparationStatus`
  values and `buttonLabel` for the same, busy and idle.
- `LibraryTest.elm` — `Page.Library`, including `summary`'s three states.
- `WaveformTest.elm` — `Waveform.barFor`, the peak-to-pixel geometry.

No view is tested. `Main.routeFor` is still only exercised indirectly.

`elm-test` needs `elm-test-rs` or the Node-based `elm-test` runner on `PATH`.
On this machine the two halves come from different places: the compiler is
Homebrew's `elm` formula, and the runner is the Node-based `elm-test`,
installed globally with npm (`/opt/homebrew/bin/elm-test` is a symlink into
`/opt/homebrew/lib/node_modules/elm-test`) — there is no `elm-test` Homebrew
formula. So **Node is a prerequisite for running these tests**, and the
"needs no `package.json` or `node_modules`" claim needs stating precisely: it
is true of *this directory and what ships from it* — no manifest here, no
dependency tree to install, nothing under `node_modules` in the built
`app.js` — and false of the dev toolchain, which needs a global npm install to
run the suite. What matters for the installed package is only the first half:
`pip install sleepmix` compiles nothing and downloads no JavaScript.
