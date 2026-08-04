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
moves.

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
`sleepmix/static/events.js`, and records a content hash of everything that fed
the build (every `.elm` file under `ui/src`, `ui/elm.json`, and
`ui/ports/events.js`) to `sleepmix/static/app.js.sha256` via
`ui/hash_sources.py`.

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

`ui/tests/` has four suites: `ApiTest.elm` (the `Api.elm` decoders, including
that an unknown status fails rather than falling through), `JobTest.elm`
(`Main.jobOutcome`, the pure function deciding whether an incoming SSE event
belongs to the job currently being tracked), `LibraryTest.elm` (`Page.Library`,
including `summary`'s three states), and `WaveformTest.elm` (`Waveform.barFor`,
the peak-to-pixel geometry). There is currently no test covering `Page.Song`
directly or `Main`'s routing (`routeFor`, the top-level `update`) — both are
exercised only indirectly, through the pieces they're built from.

`elm-test` needs `elm-test-rs` or the Node-based `elm-test` runner on `PATH`;
on this machine it's installed via Homebrew (`elm`, `elm-test`), which is why
the Elm side of this project needs no `package.json` or `node_modules` at all
— see the build note above for why that separation matters for the installed
package, though it's incidental here since `elm-test` is a dev-only tool that
never touches what ships.
