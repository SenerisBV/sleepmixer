# Plan 10: The window, weather outside the radio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stereo "window" layer to Esoterica DM Radio: felted rain, pixellated thunder, a glassy stream, soft pixellated crickets and a fire. It plays outside the radio, chosen per night, steady sounds constant and sudden sounds receding.

**Architecture:** `NightPlan` gets the pure rules (`Weather`: which night, how sudden sounds recede). `NightDSP/Window/` gets five generated sounds, each a mono `SoundSource`. `NightRadio/WindowChain` mixes the night's sounds into stereo with the open-window treatment. `RadioEngine` renders it into two more rings and adds them after the radio's mono mix, under the same master fade, ignoring the dial.

**Tech Stack:** Swift 6 package `swift/` (Swift Testing `@Test`), AVFoundation only in `RadioEngine.swift`.

**Spec:** `docs/superpowers/specs/2026-11-04-window-weather-design.md`

## Global Constraints

- Branch `feat/window-weather`. Work in `swift/`; run tests with `cd swift && swift test --skip NightDSPTests` per task unless a task says otherwise. The full `swift test` (about 15 min) runs once, in Task 6.
- Felted means the chimes' treatment: no hard attacks; every event has a raised-cosine (or smoother) attack of at least 2 ms. Pixellated means the waves' treatment: sample-and-hold at a reduced rate, bit reduction, then a gentle lowpass (see `WavesScene`: `holdHz`, `bits`, `outputCutoff`). Warm, never gritty.
- Anti-goals from the spec: nothing startling (thunder is always distant: low-passed, slow attack ≥ 0.5 s); nothing harsh; not "on top of us"; nights vary; the radio's sound, drift, static and wheel are unchanged.
- Every sound is deterministic in (seed, absolute frame) with `NightRandom`, starts cold at `startSecond`, allocates nothing per block, takes no locks, does no I/O.
- Every sound's peak stays ≤ 0.9 (−1 dBFS) at its own unit gain (a `peakIsBounded` test, like `WavesScene`).
- Sudden sounds (thunder, the fire's pops) recede on **seconds since switch-on**, via `Drift.level(clock:seed:)`, never via `DriftClock`. The window code takes no `DriftClock`.
- No API calls, no credits, no network. `NightPlan` imports only Foundation/Synchronization (`ImportGuardTests`); only `RadioEngine.swift` imports AVFoundation.
- Every invented number is a `static let` placeholder and is listed in `docs/project-state.md` under a new section "Plan 10: the window" (one table row: name, value, file, why). Each task adds its own rows.

### The placeholder values (Claude's best guesses; tune by ear on the phone)

| Name | Value |
|---|---|
| `Weather.silentRatchet` | 0.6 (sudden sounds are gone when the drift's ratchet reaches 0.6, about 4 h in) |
| `Weather.suddenFloorDB` | −18 dB (sudden-sound gain just before silence) |
| Night weights | rain 0.3, rainThunder 0.25, cricketsStream 0.25, fire 0.2 |
| `WindowChain.windowGainDB` | chosen so the window sits 8 dB under a station at drift 0 (test window: 6–10 dB) |
| Thunder | one roll every 2–6 min at full rate; 4–10 s long; attack 0.8–2 s; rumble below 600 Hz |
| Rain | 40–120 drops/s; drop attack ≥ 3 ms; wash lowpass ~3 kHz; slow swell period 20–60 s, ±3 dB |
| Stream | glassy bubbles 400–1500 Hz rising chirps, 20–60 ms; light pixellation (hold 11025 Hz, 9 bits) |
| Crickets | chirp carrier ~4.5 kHz, trains of 3 pulses, a train every 0.5–1.5 s, pauses of 5–20 s; 12 dB under rain |
| Fire | crackle bursts 2–10 ms, 1 ms min attack, band 1–4 kHz, 3–15/s; pops every 10–60 s at full rate |
| Window treatment | lowpass ~5 kHz + short `Reverb` (small room, wet ~0.2); stereo width 0.6; the fire skips both and sits nearer the centre (width 0.3) |

## Review Focus

1. **The wheel reviving thunder.** A listener who wakes at 4 a.m. and turns the dial must not get thunder back. Pinned in Task 5 (`windowTakesNoClock`, `suddenSilentDeepInNight`).
2. **The window following the needle.** Between stations, on static, and on a station, the window must be identical. Pinned in Task 6 (`windowIgnoresNeedle`).
3. **Switch-off leaving the weather playing.** Off must fade the window with the radio. Pinned in Task 6 (`offFadesWindow`).
4. **A loud first thunder.** Thunder at switch-on is at its loudest; it must still be distant and soft. Pinned in Task 4 (`thunderIsDistant`).
5. **The phone falling behind.** Doubling sound sources for stereo could underrun. Pinned in Task 5 (`windowRendersFastEnough`).

---

### Task 1: The rules of the window (NightPlan)

**Files:**
- Create: `swift/Sources/NightPlan/Weather.swift`
- Test: `swift/Tests/NightPlanTests/WeatherTests.swift`

**Interfaces:**
- Produces:
  - `public enum WindowNight: String, CaseIterable, Sendable { case rain, rainThunder, cricketsStream, fire }`
  - `public struct Sudden: Equatable, Sendable { public var rateScale: Double; public var gainDB: Double }`
  - `public enum Weather { static let silentRatchet = 0.6; static let suddenFloorDB = -18.0; public static func night(seed: UInt64) -> WindowNight; public static func sudden(_ l: DriftLevel) -> Sudden; public static func sudden(secondsSinceOn t: Double, seed: UInt64) -> Sudden }`

- [ ] **Step 1: Write the failing tests.**

```swift
@Test func nightIsDeterministicAndVaries() {
    #expect(Weather.night(seed: 7) == Weather.night(seed: 7))
    let seen = Set((0..<400).map { Weather.night(seed: UInt64($0)) })
    #expect(seen == Set(WindowNight.allCases))
}
@Test func nightWeightsRoughlyHold() {   // rain .3, rainThunder .25, cricketsStream .25, fire .2
    let n = 4000
    let c = Dictionary(grouping: (0..<n).map { Weather.night(seed: UInt64($0)) }, by: { $0 }).mapValues { Double($0.count) / Double(n) }
    #expect(abs(c[.rain]! - 0.30) < 0.04); #expect(abs(c[.fire]! - 0.20) < 0.04)
}
@Test func suddenIsFullEarlyAndSilentDeep() {
    #expect(Weather.sudden(DriftLevel(free: 0, ratchet: 0)) == Sudden(rateScale: 1, gainDB: 0))
    let deep = Weather.sudden(DriftLevel(free: 0.9, ratchet: 0.6))
    #expect(deep.rateScale == 0)
    #expect(Weather.sudden(DriftLevel(free: 1, ratchet: 0.85)).rateScale == 0)
    let mid = Weather.sudden(DriftLevel(free: 0.3, ratchet: 0.3))
    #expect(mid.rateScale > 0 && mid.rateScale < 1 && mid.gainDB < 0 && mid.gainDB > -18)
}
@Test func suddenFollowsTimeSinceOnOnly() {
    #expect(Weather.sudden(secondsSinceOn: 0, seed: 1).rateScale == 1)
    #expect(Weather.sudden(secondsSinceOn: 6 * 3600, seed: 1).rateScale == 0)
    // monotonic: it never comes back
    var last = 1.0
    for t in stride(from: 0.0, through: 6 * 3600, by: 300) {
        let r = Weather.sudden(secondsSinceOn: t, seed: 3).rateScale
        #expect(r <= last); last = r
    }
}
```

- [ ] **Step 2: Run them to see them fail.** Run: `cd swift && swift test --filter WeatherTests`. Expected: compile error, `Weather` not found.
- [ ] **Step 3: Implement `Weather.swift`.** `night`: one `NightRandom.unit(seed, 50, 0)` against the cumulative weights. `sudden(_:)`: `r = clamped(l.ratchet / silentRatchet, 0, 1)`; `rateScale = 1 - r`; `gainDB = suddenFloorDB * r`. Reads only `ratchet` (it never falls). `sudden(secondsSinceOn:seed:)` = `sudden(Drift.level(clock: t, seed: seed))`.
- [ ] **Step 4: Run them to see them pass,** with `ImportGuardTests`. Run: `swift test --filter "WeatherTests|ImportGuardTests"`.
- [ ] **Step 5: Add the "Plan 10: the window" section to `docs/project-state.md`** (a short intro pointing at the spec, and the placeholder table rows for `silentRatchet`, `suddenFloorDB` and the weights).
- [ ] **Step 6: Commit.** `git commit -m "feat(plan): the window's night and how sudden sounds recede"`

### Task 2: Felted rain (NightDSP)

**Files:**
- Create: `swift/Sources/NightDSP/Window/RainSound.swift`
- Test: `swift/Tests/NightDSPTests/WindowSoundTests.swift` (shared by Tasks 2–4)

**Interfaces:**
- Produces: `public struct RainSound: SoundSource { public init(seed: UInt64, sampleRate: Double, startSecond: Double) }`. Mono, unit gain, steady.

- [ ] **Step 1: Write the failing tests** (use `rms`, `seekLeadIn` from `Measure.swift`; `sr = 44100`).

```swift
@Test func rainIsDeterministic()     // two RainSound(seed: 5) render 10 s identically
@Test func rainPeakIsBounded()       // seeds 0..<8, 60 s each: max |x| <= 0.9
@Test func rainIsSteady()            // seed 3, 10 min: RMS of each 30 s window within 6 dB of the median window
@Test func rainIsFelted()            // seed 3, 60 s: crest factor (peak / RMS) <= 6, and the largest
                                     // sample-to-sample step <= 0.05
@Test func rainSeeksCloseToContinuous() // seekLeadIn from 120 s vs continuous: RMS of difference
                                     // at least 20 dB under the signal (the lowpass carries state)
```

- [ ] **Step 2: Run them to see them fail.** Run: `swift test --filter WindowSoundTests`.
- [ ] **Step 3: Implement `RainSound`.** Drops on a fixed grid keyed by absolute frame (as `ChimesScene` does with cells), each a short felted blip (raised-cosine windowed noise or sine burst, attack ≥ 3 ms) at a random pitch and level; plus a soft noise wash low-passed at ~3 kHz; a slow swell (20–60 s period, ±3 dB) from `NightRandom`. Values from the placeholder table.
- [ ] **Step 4: Run them to see them pass.**
- [ ] **Step 5: Add rain's rows to the placeholder table in `docs/project-state.md`.**
- [ ] **Step 6: Commit.** `git commit -m "feat(dsp): felted rain"`

### Task 3: The stream and the crickets (NightDSP)

**Files:**
- Create: `swift/Sources/NightDSP/Window/StreamSound.swift`, `swift/Sources/NightDSP/Window/CricketsSound.swift`
- Test: `swift/Tests/NightDSPTests/WindowSoundTests.swift`

**Interfaces:**
- Produces: `public struct StreamSound: SoundSource` and `public struct CricketsSound: SoundSource`, both `init(seed: UInt64, sampleRate: Double, startSecond: Double)`. Mono, steady. Crickets' own level already sits 12 dB under rain.

- [ ] **Step 1: Write the failing tests.** For each of stream and crickets: `…IsDeterministic`, `…PeakIsBounded` (seeds 0..<8, 60 s), `…IsSteady` (10 min, 30 s windows within 6 dB of the median; for crickets use 60 s windows since they pause), `…IsFelted` (largest sample step ≤ 0.05). Plus:

```swift
@Test func cricketsSitUnderRain()  // seed 1, 120 s: rms(crickets) between 10 and 14 dB under rms(rain)
@Test func cricketsPause()         // seed 1, 10 min: at least one 5 s stretch with RMS 30 dB under the overall RMS
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement both.** Stream: glassy, a soft filtered-noise bed plus sparse resonant bubble chirps (rising 400–1500 Hz, 20–60 ms, felted attack), lightly pixellated (hold 11025 Hz, 9 bits, then lowpass). Crickets: pixellated chirp trains at ~4.5 kHz, 3 pulses per train, a train every 0.5–1.5 s, with pauses of 5–20 s; very soft.
- [ ] **Step 4: Run them to see them pass.**
- [ ] **Step 5: Add their rows to the placeholder table.**
- [ ] **Step 6: Commit.** `git commit -m "feat(dsp): glassy stream and soft crickets"`

### Task 4: Thunder and the fire (NightDSP)

**Files:**
- Create: `swift/Sources/NightDSP/Window/ThunderSound.swift`, `swift/Sources/NightDSP/Window/FireSound.swift`
- Test: `swift/Tests/NightDSPTests/WindowSoundTests.swift`

**Interfaces:**
- Consumes: `Sudden`, `Curve<Sudden>` (Task 1; `Curve` is in NightPlan).
- Produces:
  - `public struct ThunderSound: SoundSource { public init(seed: UInt64, sampleRate: Double, startSecond: Double, sudden: Curve<Sudden>) }`
  - `public struct FireSound: SoundSource { public init(seed: UInt64, sampleRate: Double, startSecond: Double, sudden: Curve<Sudden>) }` (crackle steady; pops sudden)
- Each event reads `sudden` once, at its birth: it is born only if a hashed unit < its base chance × `rateScale`, and its gain is `gainDB`. So `rateScale == 0` means no new events, ever.

- [ ] **Step 1: Write the failing tests.** Deterministic and `PeakIsBounded` for both (with `Curve.constant(Sudden(rateScale: 1, gainDB: 0))`). Plus:

```swift
@Test func thunderIsDistant()   // seed 2, full rate, 30 min: at least one roll; every roll's 10–90% rise
                                // takes >= 0.5 s; energy above 1 kHz at least 30 dB under energy below 600 Hz;
                                // peak <= 0.5 (-6 dBFS)
@Test func thunderSilentWhenRateZero()  // rateScale 0, 30 min: every sample exactly 0
@Test func thunderRecedes()     // rateScale 0.25, gainDB -12 vs full: fewer rolls over 2 h and quieter loudest roll
@Test func fireCracklesSteadilyWhenPopsAreGone() // rateScale 0, 10 min: RMS > 0, 30 s windows within 6 dB of median,
                                // and peak <= 2 x the 99th-percentile |x| (no pops)
@Test func firePopsAreSoft()    // full rate, 10 min: largest sample step <= 0.1; peak <= 0.9
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement both.** Thunder: pixellated (as waves) low rumble from noise, low-passed under 600 Hz, slow attack 0.8–2 s, 4–10 s long, one every 2–6 min at full rate. Fire: crackle as sparse 2–10 ms noise bursts in 1–4 kHz with ≥ 1 ms attack plus a faint low bed; pops as rarer, louder, still-felted bursts (10–60 s apart at full rate).
- [ ] **Step 4: Run them to see them pass.** Run: `swift test --filter WindowSoundTests`.
- [ ] **Step 5: Add their rows to the placeholder table.**
- [ ] **Step 6: Commit.** `git commit -m "feat(dsp): distant pixellated thunder and the fire"`

### Task 5: The window chain (NightRadio)

**Files:**
- Create: `swift/Sources/NightRadio/WindowChain.swift`
- Test: `swift/Tests/NightRadioTests/WindowChainTests.swift`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `public struct WindowChain { public static let windowGainDB: Double; public let night: WindowNight; public init(seed: UInt64, sampleRate: Double, startSecond: Double = 0, night: WindowNight? = nil); public mutating func render(left: inout [Float], right: inout [Float], count: Int) }`. `night == nil` means `Weather.night(seed:)`. Each sound's seeds are fixed by its kind, not by the night: `NightRandom.hash(seed, 60 + k, side)` with k = rain 0, stream 1, crickets 2, thunder 3, fire 4 and side = 0 (L) / 1 (R), so the same seed's rain is identical on a rain night and a rainThunder night. It owns no `DriftClock`; seconds since switch-on are `startSecond + frames rendered / sampleRate`, and sudden sounds get `Curve { Weather.sudden(secondsSinceOn: $0, seed: seed) }`.

- [ ] **Step 1: Write the failing tests.**

```swift
@Test func eachNightHasItsSounds()   // rain night: no thunder/fire/crickets; rainThunder: thunder present in 30 min;
                                     // fire night: no rain (inspect via a test-only `activeSounds: [String]`)
@Test func windowSitsUnderAStation() // rain, cricketsStream and fire nights, 60 s, mono sum (L+R)/2: rms is 6–10 dB
                                     // under a StationChain (the-lantern-accords, no bundle, clock touched at 0)
                                     // over the same 60 s
@Test func windowIsStereo()          // rain night: L and R differ; correlation between 0.2 and 0.95
@Test func suddenSilentDeepInNight() // rainThunder, startSecond 5 h, 30 min: thunder contributes nothing
                                     // (output equals a rain night with the same seed's rain)
@Test func windowTakesNoClock()      // compile-level: WindowChain(seed:sampleRate:) builds with no DriftClock; and the
                                     // source file does not mention DriftClock (read the file, #expect no match)
@Test func windowIsDeterministic()
@Test func windowRendersFastEnough() // 60 s of WindowChain (worst night: fire or rainThunder) takes no longer than
                                     // 60 s of the three StationChains together; print the ratio
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** For each sound in the night, two instances seeded apart (L and R streams), mixed `L' = a·L + b·R` for the width (0.6; fire 0.3). Window sounds then go through a lowpass ~5 kHz and a short `Reverb` (wet ~0.2); the fire bypasses both. Scale by `windowGainDB`; then `NightFactory.masterGuard` per channel. Preallocated buffers; nothing per block. Thunder is wide but its rumble is near-mono (low frequencies).
- [ ] **Step 4: Run them to see them pass.** Run: `swift test --filter "WindowChainTests|ImportGuardTests"`.
- [ ] **Step 5: Add the window treatment and `windowGainDB` rows to the placeholder table.**
- [ ] **Step 6: Commit.** `git commit -m "feat(radio): the window chain, stereo, outside the radio"`

### Task 6: The window in the live engine

**Files:**
- Modify: `swift/Sources/NightRadio/RadioEngine.swift` (Mixer: six rings; stereo output), `swift/Sources/NightRadio/Renderer.swift` (fill the window rings)
- Test: `swift/Tests/NightRadioTests/RadioEngineTests.swift`
- Docs: `docs/project-state.md`, `ios/README.md`

**Interfaces:**
- Consumes: `WindowChain` (Task 5).
- Ring layout: indices 0–2 stations, 3 static (unchanged), 4 window left, 5 window right. `Mixer.precondition(rings.count == 6)`.
- The window rings have a fixed gain of 1 (no atomics, no dial). They use the same `readRing` underrun fades. Output: `left = guard((radioMix + windowL) × master)`, `right = guard((radioMix + windowR) × master)`. The radio's mono mix is unchanged.
- `Renderer` renders the window once per round when **both** window rings are under target, writing the same frame count to each, so they never drift apart.

- [ ] **Step 1: Write the failing tests** (manual rendering, stub fillers as the existing tests do).

```swift
@Test func windowIgnoresNeedle()   // stub filler: stations and static write 0, window rings write known L/R ramps;
                                   // needle on a station vs on static vs between: identical stereo output
@Test func windowIsStereoInOutput()// same stub: left equals windowL × master, right equals windowR × master
@Test func offFadesWindow()        // real Renderer: switch on, render 5 s, switch off, render 3 s: last 0.5 s exactly 0
@Test func radioUnchangedWithoutWindow() // stub with window rings at 0: left == right == previous mono behaviour
```

- [ ] **Step 2: Run them to see them fail.** Run: `swift test --filter RadioEngineTests`.
- [ ] **Step 3: Implement.** Keep every Plan 9 rule: no locks or allocation in the callback; engine start/stop never under the control lock.
- [ ] **Step 4: Run the NightRadio and NightPlan tests.** Run: `swift test --skip NightDSPTests`. Expected: all pass, including every Plan 9 test unchanged.
- [ ] **Step 5: Run the full suite once.** Run: `swift test` (about 15 min). Expected: all pass. Then the Release device build: `cd ios && xcodegen && xcodebuild -scheme Esoterica -destination 'generic/platform=iOS' -configuration Release CODE_SIGNING_ALLOWED=NO build`. Expected: BUILD SUCCEEDED.
- [ ] **Step 6: Docs.** In `docs/project-state.md` "Plan 10: the window": status (built, awaiting the operator's phone), what to listen for on the first night (is the window 8 dB under about right; does thunder ever startle; does the stereo read as a window; does the fire feel inside), and the deferred ideas from the spec (thunder adding crackle to the radio; rain starting/stopping mid-night). One line in `ios/README.md` that each night now has weather outside the window.
- [ ] **Step 7: Commit.** `git commit -m "feat(radio): the window plays outside the radio, in stereo"`
