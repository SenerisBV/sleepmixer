# NightEngine (Swift)

The Swift engine for Plan 7, the AM night: generated scenes (soft-mallet
chimes, pixellated waves, low warmth) heard through an AM-radio channel, bent
away from themselves by distance, slowness, fragmentation and proportion, with
three tone dials (ring, softness, vibrato) for the chimes. This is Plans 7a and
7b: three scenes, the warp, the channel, and `nightctl`, a Mac command-line
tool for auditioning them. There is no app yet.

Design and state: `docs/superpowers/specs/2026-11-02-am-night-design.md`,
`docs/architecture.md` ("The Swift engine (Plans 7a and 7b)") and
`docs/project-state.md` ("Plan 7a" and "Plan 7b", with every placeholder by
name and value). The operator has listened to the 7a set only; the 7b set is
waiting for them, and all constants are placeholders.

## Layout

| Target | Imports | Contains |
|---|---|---|
| `NightPlan` | **Foundation only; no other target** | `NightRandom`, `WarpDepth` (seven dials), `ChannelSettings`, `Curve`, `SceneKind` |
| `NightDSP` | Foundation and `NightPlan`; never AVFoundation, UIKit or AppKit | primitives, `ChimesScene`, `WavesScene`, `LowWarmthScene`, `Fragmenter`, `Distance`, `AMChannel`, `NightFactory` |
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
there is no database. The suite currently has 129 tests.

## Audition

```
swift run -c release nightctl scenes
swift run -c release nightctl audition chimes --seconds 60 --seed 1 --play
swift run -c release nightctl audition waves --distance 0.5 --slowness 0.5 --out waves.wav
swift run -c release nightctl audition waves --distance 1 --slowness 1 \
    --fragmentation 0.6 --proportion 0.8 --at 28800 --seconds 30
swift run -c release nightctl audition chimes --no-channel
swift run -c release nightctl audition chimes --ring 1 --softness 1 --vibrato 0.5
swift run -c release nightctl audition warmth --seconds 60 --play
swift run -c release nightctl audition voice --file ../esoterica/library/the-orchard-light/p01.wav \
    --seconds 90 --distance 0.6 --fragmentation 0.3 --play
```

Options: `--seconds` (above 0, up to 3600, default 60), `--at` (start second within the
night; seeks are cheap), `--seed`, `--distance`, `--slowness`,
`--fragmentation`, `--proportion` (each 0 to 1), `--ring`, `--softness`,
`--vibrato` (the chimes' tone dials, each 0 to 1; ring is how long a note
rings, softness how slowly it starts, vibrato a slow wavering; the other scenes
ignore them), `--no-channel`,
`--sample-rate` (default 44100), `--out` (default `./<scene>-<seed>.wav`) and
`--play` (afplay). It prints the path, RMS, peak and spectral centroid. Bad
input exits with code 64 and writes no file. The tool builds sound only through
`NightFactory.audition`; it can override the named fields and nothing else.

## Playing a voice file (Plan 8a)

`nightctl audition voice --file <wav>` plays a WAV (mono or stereo; PCM 16/24/32
or float32; any sample rate, resampled) through the same Fragmenter, Distance and
channel chain as the scenes. `--seconds`, `--at`, `--seed`, `--distance`,
`--fragmentation`, `--proportion`, `--no-channel` and `--play` work as above;
`--slowness`, `--ring`, `--softness` and `--vibrato` must be 0 for a voice
(a clear error otherwise); `--file` is only valid with `voice`. A file shorter
than `--seconds` ends in a 50 ms fade, then silence; it starts with a 5 ms
fade-in. The WAV is decoded once and a bad one fails before any output is
written. The Esoterica library and `esoterica/listening.sh` live in
`esoterica/` (see its README).

## The listening set

`swift/listening/render.sh` regenerates ten 60-second files (seed 1):
the waves (plain, at `--distance 0.5 --slowness 0.5`, at `--distance 1
--slowness 1 --fragmentation 0.6 --proportion 0.8`, and plain with
`--no-channel`); the soft chimes (`chimes-soft-plain`, `chimes-soft-sleepy` at
`--ring 1 --softness 1`, `chimes-soft-deep` at `--ring 1 --softness 1 --vibrato
1 --distance 0.6 --slowness 0.5`, and `chimes-soft-nochannel`); and the
warmth (`warmth-plain`, `warmth-nochannel`). It also writes `measurements.txt`.
The WAVs are git-ignored (the repository ignores `*.wav`), so run the script
to get them. The old bell-chime files from 7a no longer exist.
