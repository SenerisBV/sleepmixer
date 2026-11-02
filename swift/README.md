# NightEngine (Swift)

The Swift engine for Plan 7, the AM night: generated scenes (rich round chimes,
pixellated waves) heard through an AM-radio channel, bent away from themselves
by distance, slowness, fragmentation and proportion. This is Plan 7a, the first
slice: two scenes, the warp, the channel, and `nightctl`, a Mac command-line
tool for auditioning them. There is no app yet.

Design and state: `docs/superpowers/specs/2026-11-02-am-night-design.md`,
`docs/architecture.md` ("The Swift engine (Plan 7a)") and
`docs/project-state.md` ("Plan 7a", with every placeholder by name and value).
Nobody has listened to the output yet; all constants are placeholders.

## Layout

| Target | Imports | Contains |
|---|---|---|
| `NightPlan` | **Foundation only; no other target** | `NightRandom`, `WarpDepth`, `ChannelSettings`, `Curve`, `SceneKind` |
| `NightDSP` | Foundation and `NightPlan`; never AVFoundation, UIKit or AppKit | primitives, `ChimesScene`, `WavesScene`, `Fragmenter`, `Distance`, `AMChannel`, `NightFactory` |
| `NightCLI` | `NightDSP`, `NightPlan`, ArgumentParser | the `scenes` and `audition` commands |
| `nightctl` | `NightCLI` | `main.swift` |

**The layout rule: `NightPlan` is pure.** It has no dependency on the DSP and
imports only Foundation, so the planner can be built, tested and replayed
without rendering. Two tests (`ImportGuardTests`) fail if either target's
imports drift. Put anything the planner and the audio both need in
`NightPlan`; put anything that makes sound in `NightDSP`.

## Build and test

Requires Swift 6 (macOS 15 / iOS 18 targets).

```
cd swift
swift build -c release
swift test -c release
```

**Always test with `-c release`.** Per-sample DSP in debug is 10 to 50 times
slower and the suite renders minutes of audio. The tests are pure unit tests;
there is no database. The suite currently has 80 tests.

## Audition

```
swift run -c release nightctl scenes
swift run -c release nightctl audition chimes --seconds 60 --seed 1 --play
swift run -c release nightctl audition waves --distance 0.5 --slowness 0.5 --out waves.wav
swift run -c release nightctl audition waves --distance 1 --slowness 1 \
    --fragmentation 0.6 --proportion 0.8 --at 28800 --seconds 30
swift run -c release nightctl audition chimes --no-channel
```

Options: `--seconds` (0 to 3600, default 60), `--at` (start second within the
night; seeks are cheap), `--seed`, `--distance`, `--slowness`,
`--fragmentation`, `--proportion` (each 0 to 1), `--no-channel`,
`--sample-rate` (default 44100), `--out` (default `./<scene>-<seed>.wav`) and
`--play` (afplay). It prints the path, RMS, peak and spectral centroid. Bad
input exits with code 64 and writes no file. The tool builds sound only through
`NightFactory.audition`; it can override the named fields and nothing else.

## The listening set

`swift/listening/render.sh` regenerates eight 60-second files (seed 1): chimes
and waves, each plain, at `--distance 0.5 --slowness 0.5`, at
`--distance 1 --slowness 1 --fragmentation 0.6 --proportion 0.8`, and plain
with `--no-channel`. It also writes `measurements.txt`. The WAVs are
git-ignored (the repository ignores `*.wav`), so run the script to get them.
