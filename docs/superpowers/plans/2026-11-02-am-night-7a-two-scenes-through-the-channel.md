# Plan 7a: two scenes through the channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The operator can run one command on the Mac and hear rich round chimes or pixellated waves, at any warp depth, with or without the AM channel. This is milestone 1 of the AM-night design.

**Architecture:** A new Swift package at `swift/` with three library targets and one executable. `NightPlan` is pure data and arithmetic (warp depths, channel settings, curves over time, a counter-based random generator) and depends on nothing. `NightDSP` depends on `NightPlan` and makes sound: DSP primitives, the two scenes, the two warp processors (distance and fragmentation), the AM channel, and `NightFactory`, the single function every front end uses to build a graph. `NightCLI` parses arguments into a `NightFactory` request, and `nightctl` is a three-line `main` that calls it. Everything is mono, `Float`, and seekable: any second of any render can be computed without rendering what came before.

**Tech Stack:** Swift 6 (toolchain 6.4 installed), Swift Package Manager, Swift Testing (`import Testing`), `swift-argument-parser` 1.5.0. Foundation only in `NightPlan` and `NightDSP`, with no AVFoundation, UIKit or AppKit, so the iPhone app can use both unchanged.

**Spec:** `docs/superpowers/specs/2026-11-02-am-night-design.md`. Read "How it gets made", "The scenes", "The AM channel" and "The warping" before starting.

**Not in this plan:** the night planner and arc, memory replay, bleed/whistle/tuning sweeps (all of which need a night to draw from), the other scenes, voices, and the iPhone app. **The motion spike** (Plan 6's "Spike: motion overnight", kept by Plan 7) runs alongside this plan on the phone and is not part of it.

## Global Constraints

- Package root `swift/`, `swift-tools-version: 6.0`, platforms `.macOS(.v15), .iOS(.v18)`.
- `NightPlan` has **no target dependencies and imports only Foundation** (spec: "the planner lives in its own module … with no dependency on the DSP module").
- `NightPlan` and `NightDSP` import only Foundation (and `NightPlan`), never AVFoundation, UIKit or AppKit.
- Sample format: mono `Float`, sample rate passed in everywhere (default 44100). Nothing may assume 44100.
- **No transients** (spec anti-goal): every event and every gate has a fade; crackle is "soft, continuous, below event level. Never pops."
- **One factory** (spec: "the app and the Mac tool construct the night through the same single factory function, and the tool may only *override* named fields on top of it"). `nightctl` builds sound only via `NightFactory.audition`.
- All randomness comes from `NightRandom` (spec: "one simple, specified generator in Swift").
- Every invented number is a **placeholder** and is recorded in `docs/project-state.md` in Task 8 (user CLAUDE.md rule).
- Run tests from `swift/` with **`swift test -c release`**. Per-sample DSP in debug is 10–50× slower, and the suite renders minutes of audio. These are pure unit tests; there is no database.
- **No agent has ears** (`docs/project-state.md`). Implementers write listening samples and report measurements; they never describe how something sounds and never play audio. All listening is the operator's, in Task 8's hand-off.
- **Seeking is the factory's job.** Components start cold at whatever `startSecond` they're given. To render from `T`, `NightFactory` starts every component at `max(0, T − 6)` and discards the lead-in (6 s ≥ the longest stateful tail: 4.5 s reverb plus filter settling). Component-level seek tests use the test helper `seekLeadIn` (Task 2), which does the same.

## Review Focus

1. **Warp and channel values at or past their edges** (0, 1, negative, >1, NaN): clamped on construction, output finite and peak ≤ 1.0. Test in Task 1 (clamping) and Task 7 (corner renders).
2. **Hour-eight offsets**: rendering from second 28,800 must sound like rendering from second 0, with no phase drift, NaN or precision hiss from a large `Float` time. Test in Task 3 and Task 4.
3. **48 kHz** (iPhone hardware often runs at 48000): band corners and timings must be in Hz and seconds, not samples. Test in Task 6.
4. **Bad command-line input** (unknown scene, depth 1.5, negative seconds): a clear error, a nonzero exit, and no file written. Test in Task 7.
5. **Peak safety**: scene + reverb + saturation + hiss at maximum settings must never exceed 1.0 when written to WAV. Test in Task 7.

---

## File structure

```
swift/
  Package.swift
  Sources/
    NightPlan/
      NightRandom.swift      counter-based hash RNG
      WarpDepth.swift        the four warp controls, clamped
      ChannelSettings.swift  AM channel parameters, clamped, with .early defaults
      Curve.swift            Curve<Value>: a value as a function of seconds
      SceneKind.swift        the scene catalogue (chimes, waves)
    NightDSP/
      Primitives/Biquad.swift       RBJ biquad (lowpass, highpass, peaking)
      Primitives/Reverb.swift       small Schroeder/Freeverb-style mono reverb
      Primitives/Envelope.swift     raised-cosine fades, attack/decay envelope
      Primitives/WAVWriter.swift    float32 mono WAV writer
      SoundSource.swift             SoundSource / Processor protocols
      Scenes/ChimesScene.swift
      Scenes/WavesScene.swift
      Warp/Distance.swift
      Warp/Fragmenter.swift
      Channel/AMChannel.swift
      NightFactory.swift            AuditionRequest + NightFactory.audition
    NightCLI/
      NightCtl.swift                ArgumentParser root + `audition` and `scenes`
    nightctl/
      main.swift                    NightCtl.main()
  Tests/
    NightPlanTests/…               one file per NightPlan source
    NightDSPTests/…                one file per scene/processor + Measure.swift
    NightCLITests/NightCtlTests.swift
```

---

### Task 1: The package, and `NightPlan`

**Files:**
- Create: `swift/Package.swift`, every file under `swift/Sources/NightPlan/`, `swift/Sources/NightDSP/SoundSource.swift` (protocols only, so the target compiles), `swift/Tests/NightPlanTests/NightPlanTests.swift`, `swift/Tests/NightPlanTests/ImportGuardTests.swift`
- Modify: `.gitignore` (add `swift/.build/` and `swift/.swiftpm/`)

**Interfaces:**
- Produces:
  - `public enum NightRandom { static func hash(_ seed: UInt64, _ stream: UInt64, _ index: UInt64) -> UInt64; static func unit(_:_:_:) -> Double /* [0,1) */; static func signed(_:_:_:) -> Double /* [-1,1) */ }`
  - `public struct WarpDepth: Equatable, Sendable { public var distance, slowness, fragmentation, proportion: Double; public init(distance: Double = 0, slowness: Double = 0, fragmentation: Double = 0, proportion: Double = 0); public static let plain: WarpDepth }`: every field clamped to `0...1` in `init` and in each setter; NaN becomes 0.
  - `public struct ChannelSettings: Equatable, Sendable { lowCornerHz, highCornerHz, hissLevelDB, crackleLevelDB, fadeDepth, fadeRateHz, squash: Double; public static let early: ChannelSettings }` with `early` = low 180, high 4500, hiss −48, crackle −54, fadeDepth 0.25, fadeRate 0.05, squash 0.5 (placeholders). Clamps: low 40…1000, high 800…8000 with high ≥ low × 2, levels −96…−20, fadeDepth and squash 0…1, fadeRate 0.005…1.
  - `public struct Curve<Value: Sendable>: Sendable { public init(_ at: @escaping @Sendable (Double) -> Value); public func callAsFunction(_ second: Double) -> Value; public static func constant(_ v: Value) -> Curve }`
  - `public enum SceneKind: String, CaseIterable, Sendable { case chimes, waves }`
  - In `NightDSP/SoundSource.swift`: `public protocol SoundSource { mutating func render(into out: inout [Float], count: Int) }` (fills `out[0..<count]`, `out.count >= count`) and `public protocol Processor { mutating func process(_ buffer: inout [Float], count: Int) }`.

- [ ] **Step 1: Write the package manifest** with only the targets that have sources yet: `NightPlan` (no deps), `NightDSP` (deps: `NightPlan`), and test target `NightPlanTests`. (SwiftPM refuses a target with no sources; Task 2 adds `NightDSPTests`, and Task 7 adds `NightCLI`, `nightctl`, `NightCLITests` and the `swift-argument-parser` dependency.) Add the `.gitignore` lines.

- [ ] **Step 2: Write the failing tests** in `NightPlanTests.swift`:

```swift
@Test func hashIsDeterministicAndSpread() {
    #expect(NightRandom.hash(7, 1, 42) == NightRandom.hash(7, 1, 42))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(7, 1, 43))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(7, 2, 42))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(8, 1, 42))
    let u = (0..<10_000).map { NightRandom.unit(1, 0, UInt64($0)) }
    #expect(u.allSatisfy { $0 >= 0 && $0 < 1 })
    #expect(abs(u.reduce(0, +) / 10_000 - 0.5) < 0.02)
}
@Test func hashGoldenValue() {   // pins the algorithm so Swift on every device agrees
    #expect(NightRandom.hash(0, 0, 0) == 0xE220A8397B1DCDAF)   // SplitMix64's canonical first output for seed 0
}
@Test func warpClampsEveryField() {
    let w = WarpDepth(distance: 1.5, slowness: -0.2, fragmentation: .nan, proportion: 0.4)
    #expect(w == WarpDepth(distance: 1, slowness: 0, fragmentation: 0, proportion: 0.4))
}
@Test func channelClampsAndKeepsAnOctave() {
    var c = ChannelSettings.early; c.highCornerHz = 200; c.lowCornerHz = 300
    #expect(c.highCornerHz >= c.lowCornerHz * 2)
}
@Test func constantCurve() { #expect(Curve.constant(3.0)(28_800) == 3.0) }
```

`ImportGuardTests.swift`: read every `.swift` file under `Sources/NightPlan` (path found relative to `#filePath`) and assert none contains a line matching `^import (?!Foundation$)`. Read every file under `Sources/NightDSP` and assert no `import AVFoundation|UIKit|AppKit|SwiftUI`.

- [ ] **Step 3: Run** `cd swift && swift test -c release --filter NightPlanTests`. Expected: FAIL (types not defined).

- [ ] **Step 4: Implement the `NightPlan` files.** `hash` is SplitMix64 over a combined key, exactly:

```swift
var z = seed &+ 0x9E3779B97F4A7C15 &* (stream &+ 1)
z ^= index &* 0xD1B54A32D192ED03
z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
return z ^ (z >> 31)
```

`unit` = `Double(hash >> 11) * 0x1p-53`; `signed` = `unit * 2 - 1`. With stream 0 and index 0 this reduces to SplitMix64's first output for seed 0, which is what `hashGoldenValue` pins. Clamping lives in `didSet` plus `init`. For `ChannelSettings`, enforce the octave by raising `highCornerHz`.

- [ ] **Step 5: Run** `swift test -c release`. Expected: all PASS, and `swift build` builds every target.

- [ ] **Step 6: Commit**

```bash
git add .gitignore swift
git commit -m "feat(swift): NightEngine package and the pure NightPlan module"
```

---

### Task 2: DSP primitives and the WAV writer

**Files:**
- Create: `swift/Sources/NightDSP/Primitives/{Biquad,Reverb,Envelope,WAVWriter,Analysis}.swift`, `swift/Tests/NightDSPTests/{PrimitivesTests,Measure}.swift`
- Modify: `swift/Package.swift` (add test target `NightDSPTests`, deps `NightDSP`)

**Interfaces:**
- Produces:
  - `public struct Biquad { public static func lowpass(cutoff: Double, q: Double = 0.7071, sampleRate: Double) -> Biquad; highpass(...); peaking(center: Double, q: Double, gainDB: Double, sampleRate: Double) -> Biquad; public mutating func process(_ x: Float) -> Float; public mutating func setCoefficients(from other: Biquad) }` (RBJ cookbook, transposed direct form II, state kept across `setCoefficients`)
  - `public struct Reverb { public init(sampleRate: Double, seed: UInt64); public var decaySeconds: Double; public mutating func process(_ x: Float) -> Float /* wet only */ }` (4 parallel combs + 2 allpasses, delay lengths in *seconds* scaled to the sample rate, comb feedback set from `decaySeconds`)
  - `public enum Envelope { public static func raisedCosine(_ t: Double) -> Double /* 0→1 over t∈[0,1], clamped */; public static func attackDecay(t: Double, attack: Double, decay: Double) -> Double /* 0 before 0, raised-cosine rise over attack, exp(-(t-attack)/decay) after */ }`
  - `public enum WAVWriter { public static func write(_ samples: [Float], sampleRate: Int, to url: URL) throws }` (IEEE float32, mono, `WAVE_FORMAT_IEEE_FLOAT` = 3)
  - `public enum Analysis { public static func rmsDB(_ x: ArraySlice<Float>) -> Double; public static func peakDB(_ x: [Float]) -> Double; public static func centroidHz(_ x: [Float], sampleRate: Double) -> Double; public static func bandEnergyRatio(_ x: [Float], sampleRate: Double, above hz: Double) -> Double; public static func bandEnergyRatio(_ x: [Float], sampleRate: Double, below hz: Double) -> Double }` in `NightDSP/Primitives/Analysis.swift` (public because `nightctl` prints these; centroid = mean over 4096-sample windows of a naive or Accelerate-free DFT, hop 4096, at most 64 windows spread across the buffer)
  - Test-only, in `Measure.swift`: `func rms(_ x: ArraySlice<Float>) -> Double` (linear), `func sine(_ hz: Double, seconds: Double, sr: Double) -> [Float]`, `func noise(seconds: Double, sr: Double, seed: UInt64) -> [Float]` (from `NightRandom.signed`), a test helper `func seekLeadIn<S>(_ make: (Double) -> S, from: Double, seconds: Double, sr: Double) -> [Float]` that builds the component at `max(0, from − 6)`, renders, and drops the lead-in (for processors, a variant that takes the input signal), and `func writeIfListening(_ x: [Float], name: String, sr: Double)`, which writes `name.wav` with `WAVWriter` into `$NIGHT_LISTEN_DIR` only when that environment variable is set, and otherwise does nothing.

- [ ] **Step 1: Write the failing tests** in `PrimitivesTests.swift`:
  - `lowpassAttenuatesAboveCutoff`: a 1 kHz lowpass at 44100 passes a 200 Hz sine within 1 dB and attenuates a 5 kHz sine by at least 20 dB. Repeat at 48000.
  - `highpassAttenuatesBelowCutoff`: 300 Hz highpass, 60 Hz sine ≥ 18 dB down, 2 kHz within 1 dB.
  - `reverbTailMatchesDecay`: an impulse into `Reverb(decaySeconds: 2)`: the RMS of the window 1.9–2.1 s is between −75 and −45 dB relative to the 0–0.1 s window, and the output is finite.
  - `attackDecayIsSoft`: `attackDecay(t: 0, attack: 0.02, decay: 1) == 0`, value at `t = 0.01` is 0.5 ± 0.01, at `0.02` is 1, monotone non-decreasing on `[0, 0.02]`.
  - `analysisAgrees`: `Analysis.centroidHz` of a 1 kHz sine is 1000 ± 30 Hz; `rmsDB` of a full-scale sine is −3.01 ± 0.05.
  - `wavRoundTrip`: write 1000 samples, read the file back with `Data`; bytes 0–3 `RIFF`, 8–11 `WAVE`, format tag 3 at offset 20, channels 1, sample rate field equals 48000, and the float payload equals the input.

- [ ] **Step 2: Run** `swift test -c release --filter PrimitivesTests`. Expected: FAIL.
- [ ] **Step 3: Implement the five primitives** with the signatures above.
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(swift): filters, reverb, envelopes and a WAV writer"`

---

### Task 3: Rich round chimes

**Files:**
- Create: `swift/Sources/NightDSP/Scenes/ChimesScene.swift`, `swift/Tests/NightDSPTests/ChimesSceneTests.swift`
- Modify: `swift/Sources/NightDSP/SoundSource.swift` (add the `Scene` protocol)

**Interfaces:**
- Consumes: `NightRandom`, `WarpDepth`, `Curve`, `SceneKind`, `Envelope`, `Biquad`.
- Produces:
  - `public protocol Scene: SoundSource { static var kind: SceneKind { get }; var elements: [String] { get }; init(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, startSecond: Double) }`
  - `public struct ChimesScene: Scene` with `elements == ["strike", "body", "bloom", "beating"]`.

**How it's made (the decisions the implementer can't guess):**
- **Strikes live on a fixed grid** of cells 2.2 s long (placeholder). Cell `i` holds a strike when `NightRandom.unit(seed, 1, i) < 0.6 / (1 + 2 × slowness)` (fewer strikes as it slows), at offset `unit(seed, 2, i) × 1.6 s`. A fixed grid with a probability is what keeps the scene seekable while slowness changes.
- **Each strike is frozen at its birth**: it reads `warp(birthSecond)` once and keeps those values for its whole life.
- **Pitch:** the scene root is drawn once per seed from 196–392 Hz. Each strike picks a degree of a major pentatonic set over two octaves (`unit(seed, 3, i)`), lowered by `slowness × 3` semitones.
- **Elements:**
  - **strike:** a soft mallet, bandpassed hashed noise. Attack 20 ms (placeholder, spec "no transients"), decay 80 ms.
  - **body:** partials at ratios `[1.0, 2.0, 2.76, 4.07]`, with decays `[6, 3, 2, 1.2]` s × `(1 + 2 × slowness)` and amplitudes `[1, 0.5, 0.35, 0.2]`.
  - **bloom:** the fundamental and an octave below, with a 1.5 s attack and a 12 s decay × `(1 + slowness)`.
  - **beating:** two partials at the fundamental ± 0.35 Hz, with an 8 s decay.
- **Proportion:** a favoured element is drawn per strike (`unit(seed, 4, i)`). Its gain is `+6 × proportion` dB, and every other element's is `−12 × proportion` dB.
- **Seekability:** every oscillator phase is `2π f (t − birth)`, computed in `Double` from the absolute frame. The strike's mallet filter is **per strike, with its state zeroed at birth and run from the strike's own birth frame**, never a filter shared across strikes, so it's a pure function of the frame too. Rendering from `startSecond` re-renders every strike born up to 60 s earlier from its birth (the longest tail at maximum slowness, 36 s, plus margin). The sum order is fixed (by cell index), so a seek is **bit-identical** to a continuous render.
- **Level:** scale so that a dense passage peaks around −6 dBFS before any processing.

- [ ] **Step 1: Write the failing tests** (Swift Testing, `sr = 44100` unless stated):
  - `sameSeedSameSound`: two 20 s renders with seed 7 are equal. Seeds 7 and 8 differ.
  - `seekIsExact`: render 0–40 s continuously, then `startSecond: 25` for 15 s. The slices are equal (`==`, not approximate).
  - `hourEightIsHealthy`: a 60 s render at `startSecond: 28_800` is finite, and its RMS averaged over seeds 1…5 is within 6 dB of the same average at 0 s, and its peak is ≤ 1.
  - `slownessThinsAndLowers`: over 120 s × seeds 1…5, `slowness: 1` has at most 60% of the strike count of `slowness: 0` (count via a test-visible `static func strikeTimes(seed:sampleRate:warp:from:to:) -> [Double]`), and a lower spectral centroid.
  - `proportionReweights`: with `proportion: 1`, the per-strike element gains (from a test-visible `static func elementGains(seed:index:warp:) -> [Double]`) contain exactly one +6 dB element and the rest at −12 dB.
  - `strikeAttackIsSoft`: `ChimesScene.strikeAttack >= 0.02`, and the scene uses `Envelope.attackDecay` with it (whose softness Task 2 already tests).
  - `listeningSample`: renders 60 s at plain warp and passes it to `writeIfListening(_, name: "chimes-plain", sr:)`. It always passes.
  - `nothingAbove6k`: `Analysis.bandEnergyRatio(render, sampleRate: sr, above: 6000) < 0.05` (so the round bell isn't brittle even before the channel).

- [ ] **Step 2: Run** `swift test -c release --filter ChimesSceneTests`. Expected: FAIL.
- [ ] **Step 3: Implement `ChimesScene`** to the decisions above.
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Write a listening sample.** Run `NIGHT_LISTEN_DIR=<scratchpad> swift test -c release --filter listeningSample`. Report the file path and its RMS, peak and centroid (via `Analysis`) in the task report. Don't play it and don't describe its sound: the operator listens in Task 8.
- [ ] **Step 6: Commit** `git commit -m "feat(swift): rich round chimes, seekable on a fixed grid"`

---

### Task 4: Pixellated waves

**Files:**
- Create: `swift/Sources/NightDSP/Scenes/WavesScene.swift`, `swift/Tests/NightDSPTests/WavesSceneTests.swift`

**Interfaces:**
- Consumes: `Scene`, `NightRandom`, `Biquad`, `Envelope`, `Curve<WarpDepth>`.
- Produces: `public struct WavesScene: Scene` with `elements == ["swell", "break", "wash"]`, and `public func envelope(at second: Double) -> Double` (the summed wave envelope, test-visible, used by `noGatedCrunch`).

**How it's made:**
- **Waves are born on a fixed 6 s grid** (placeholder). Wave `i` exists when `unit(seed, 11, i) < 0.85 / (1 + slowness)`. Its length is `7 + unit(seed, 12, i) × 5` s × `(1 + slowness)`, frozen at birth. Waves overlap and sum.
- **Source noise is hashed per frame**, `NightRandom.signed(seed, 13, frame)`, so it's identical however you arrive at a frame.
- **Each wave's shape:**
  - **swell:** low noise, lowpassed at 400 Hz, raised-cosine up over 45% of its length.
  - **break:** mid noise, bandpassed 800–2500 Hz, peaking at 55%.
  - **wash:** high-mid hiss, highpassed at 1500 Hz, an exponential tail over the last 50%.
  - Proportion works like the chimes: one element +6 × p dB, the others −12 × p dB, drawn per wave.
- **"Pixellated"** (spec: "rendered at low resolution (bit depth and sample rate stepped down) so it reads as *remembered* surf"). The summed wave signal is normalised to its slow envelope, sample-and-held at `5512 Hz × (1 − 0.4 × slowness)`, quantised to 7 bits, re-multiplied by the envelope (so quiet passages don't turn into gated crunch), then lowpassed at 4 kHz. All placeholders.
- **Seekability:** the filters carry state, so a seek is *approximately* equal to a continuous render, not exactly. The scene starts cold. The lead-in is the factory's job (Global Constraints), and the test uses `seekLeadIn`.

- [ ] **Step 1: Write the failing tests:**
  - `sameSeedSameSound`, as for the chimes.
  - `seekIsClose`: continuous 0–40 s against `seekLeadIn` to 25 s for 15 s. The difference's RMS is at least 40 dB below the signal's RMS.
  - `hourEightIsHealthy`, as for the chimes.
  - `slownessLengthensWaves`: over 300 s × seeds 1…5, the mean wave length (from a test-visible `static func waveSpans(seed:warp:from:to:) -> [ClosedRange<Double>]`) at `slowness: 1` is ≥ 1.8× the length at 0.
  - `pixellationIsAudible`: with the same seed, `Analysis.bandEnergyRatio(above: 2800)` of the render differs measurably from a render with pixellation disabled through a test-visible `var pixellate = true`. This guards against the quantiser silently doing nothing.
  - `listeningSample`: as for the chimes, named `waves-plain`.
  - `noGatedCrunch`: in passages where the wave envelope is below −40 dBFS, the render's RMS is also below −34 dBFS (quantisation noise doesn't escape the envelope).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `WavesScene`.**
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Write a listening sample**, the same way as Task 3. Report it; don't judge it.
- [ ] **Step 6: Commit** `git commit -m "feat(swift): pixellated waves"`

---

### Task 5: The warp processors: distance and fragmentation

**Files:**
- Create: `swift/Sources/NightDSP/Warp/{Distance,Fragmenter}.swift`, `swift/Tests/NightDSPTests/WarpTests.swift`

**Interfaces:**
- Consumes: `Processor`, `Biquad`, `Reverb`, `Envelope`, `NightRandom`, `Curve<WarpDepth>`.
- Produces:
  - `public struct Distance: Processor { public init(sampleRate: Double, seed: UInt64, warp: Curve<WarpDepth>, startSecond: Double) }`. It reads `warp(t).distance`, updated every 512 frames and glided with a 2 s one-pole smoother (placeholder).
    - At depth `d`, the lowpass corner is `8000 × (400/8000)^d` Hz (8 kHz → 400 Hz), the direct gain is `1 − 0.8d`, the reverb send is `0.15 + 0.7d`, and the reverb decay is `1.2 + 3.3d` s. All placeholders. (The spec's "lowpass never above the brightness ceiling" arrives with the arc in milestone 2. Leave the corner as a computed property, `public func cornerHz(at second: Double) -> Double`, so it can be capped.)
  - `public struct Fragmenter: Processor { public init(sampleRate: Double, seed: UInt64, warp: Curve<WarpDepth>, startSecond: Double); public static let cellSeconds = 3.0; public static let fadeSeconds = 0.4 }`. Time is cut into 3 s cells. Cell `i` is *present* when `unit(seed, 21, i) ≥ 0.7 × fragmentation(at cell start)`. A boundary between a present cell and an absent one crossfades over 0.4 s with a raised cosine, centred on the boundary. The gain at any frame is a pure function of the frame, so seeking is exact.

- [ ] **Step 1: Write the failing tests:**
  - `distanceZeroIsNearlyTransparent`: a 500 Hz sine through `Distance` at depth 0 keeps its RMS within 2 dB (the reverb send of 0.15 adds a little).
  - `distanceDarkens`: pink-ish noise (filtered hashed noise) at depth 1 has a centroid at most 40% of the depth-0 centroid. The same holds at 48000.
  - `distanceGlides`: a curve that jumps 0 → 1 at 10 s. `cornerHz` at 10.1 s is still above 4000 Hz, at 16 s it's below 800.
  - `fragmentationZeroIsUnity`: gain is 1 everywhere over 120 s.
  - `fragmentationOneLeavesAboutThirtyPercent`: over 3600 s, the fraction of present cells is 0.30 ± 0.05.
  - `fragmentGainIsSmooth`: across 600 s at depth 1, the largest change in gain between consecutive frames is ≤ `π / (2 × fadeSeconds × sr) × 1.01` (a raised cosine's maximum slope). No steps.
  - `fragmentSeekIsExact`: the gains from `startSecond: 100` equal the continuous gains from 100 s.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement both processors.**
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(swift): distance and fragmentation"`

---

### Task 6: The AM channel

**Files:**
- Create: `swift/Sources/NightDSP/Channel/AMChannel.swift`, `swift/Tests/NightDSPTests/AMChannelTests.swift`

**Interfaces:**
- Consumes: `Processor`, `Biquad`, `NightRandom`, `Curve<ChannelSettings>`, `Envelope`.
- Produces: `public struct AMChannel: Processor { public init(sampleRate: Double, seed: UInt64, settings: Curve<ChannelSettings>, startSecond: Double) }`.

**How it's made.** Settings are read every 512 frames and glided over 2 s. The chain:

1. **Add hiss and crackle.**
   - Hiss is hashed noise lowpassed at 6 kHz, at `hissLevelDB`.
   - Crackle is a sparse rain of grains. Each grain is 3–8 ms of noise under a full Hann window (never a step), at about 40 grains per second. Each grain's level is drawn from `crackleLevelDB − 6 … crackleLevelDB` dB. Crackle stays texture: no single grain more than 6 dB above `crackleLevelDB`.
2. **Night fading.** A gain of `1 − fadeDepth × s(t)`, where `s(t)` is smooth noise in 0…1: cosine interpolation between `unit(seed, 31, k)` values placed every `1/fadeRateHz` seconds.
   - Selective fading is a peaking filter at `−9 × fadeDepth × s₂(t)` dB. Its centre sweeps 600–2500 Hz, driven by a second smooth-noise stream (`seed, 32`).
3. **Band.** A 2nd-order highpass at `lowCornerHz`, then a 4th-order lowpass (two cascaded biquads) at `highCornerHz`.
4. **Squash and warmth.**
   - An RMS compressor: 50 ms attack, 400 ms release, threshold −24 dBFS, ratio `1 + 3 × squash`.
   - Then `tanh(drive × x) / tanh(drive)`, with `drive = 1 + 2 × squash`.

All values not given in `ChannelSettings` are placeholders.

- [ ] **Step 1: Write the failing tests:**
  - `bandIsNarrow`: white hashed noise through the channel with `.early` puts less than 3% of its energy above 6 kHz and less than 5% below 120 Hz, both measured with `Analysis.bandEnergyRatio` (true DFT band energy, not a filter whose skirt would count in-band energy). At 48000 the same holds, and the centroid is within 10% of the 44100 centroid.
  - `silenceInHissOut`: silence in gives an output RMS between −60 and −40 dBFS (hiss at −48 plus crackle), and its peak is below −30 dBFS. The crackle stays texture.
  - `noClicksFromCrackle`: silence in, 60 s. Split the output into 5 ms windows. No window's RMS exceeds the median window RMS by more than 15 dB.
  - `fadingMoves`: a steady 1 kHz sine with `fadeDepth: 1, fadeRateHz: 0.2` over 120 s. Its 1 s RMS values span at least 6 dB. With `fadeDepth: 0`, they span less than 1 dB.
  - `squashWarmsWithoutClipping`: a 0 dBFS sine at maximum `squash` gives a peak ≤ 1.0 and a finite output.
  - `seekIsClose`: continuous against `seekLeadIn` at 30 s, with the same input signal. The difference is at least 40 dB below the signal.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `AMChannel`.**
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(swift): the AM channel"`

---

### Task 7: `NightFactory` and `nightctl`

**Files:**
- Create: `swift/Sources/NightDSP/NightFactory.swift`, `swift/Sources/NightCLI/NightCtl.swift` (including `extension SceneKind: ExpressibleByArgument`, which can't live in `NightPlan`), `swift/Sources/nightctl/main.swift`, `swift/Tests/NightDSPTests/NightFactoryTests.swift`, `swift/Tests/NightCLITests/NightCtlTests.swift`
- Modify: `swift/Package.swift` (add dependency `https://github.com/apple/swift-argument-parser` `from: "1.5.0"`, targets `NightCLI` (deps `NightDSP`, `ArgumentParser`), executable `nightctl` (deps `NightCLI`), test target `NightCLITests`)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `public struct AuditionRequest: Equatable, Sendable`, with fields and defaults:
    - `scene: SceneKind`
    - `seconds: Double = 60`
    - `startSecond: Double = 0`
    - `seed: UInt64 = 1`
    - `warp: WarpDepth = .plain`
    - `channel: Bool = true`
    - `channelSettings: ChannelSettings = .early`
    - `sampleRate: Double = 44100`
  - `public enum NightFactory { public static func audition(_ r: AuditionRequest) -> [Float] }`
    - The chain is scene → `Fragmenter` → `Distance` → `AMChannel` (if `channel`) → master guard.
    - The master guard is a soft limiter with a ceiling of −1 dBFS: unity below −6 dBFS and a tanh knee above.
    - Each component gets its own seed: `NightRandom.hash(seed, componentIndex, 0)`.
    - The warp and settings are wrapped as `Curve.constant`.
    - Seeking: every component starts at `max(0, startSecond − 6)`, and the lead-in is discarded (Global Constraints).
    - This is **the** single factory (Global Constraints).
  - `NightCLI`: `public struct NightCtl: ParsableCommand` with subcommands:
    - **`scenes`** prints one `SceneKind.rawValue` per line.
    - **`audition`** takes:
      - the argument `<scene>`;
      - options `--seconds`, `--at` (startSecond), `--seed`, `--distance`, `--slowness`, `--fragmentation` and `--proportion`;
      - the flag `--no-channel`;
      - `--sample-rate`;
      - `--out <path>`, defaulting to `./<scene>-<seed>.wav`;
      - the flag `--play`, which runs `/usr/bin/afplay <out>` after writing.

      It has `public func request() -> AuditionRequest`, and `validate()` rejects an unknown scene, a depth outside 0…1, seconds ≤ 0 or > 3600, and `--at` < 0. `run()` calls `NightFactory.audition`, then `WAVWriter`, then prints one line, `<out>  rms <x> dB  peak <y> dB  centroid <z> Hz` (from `Analysis`), then optionally runs afplay.
  - `nightctl/main.swift`: `NightCtl.main()`.

- [ ] **Step 1: Write the failing tests:**
  - `NightFactoryTests.everyCornerIsSafe`: for each scene, and every combination of each warp field ∈ {0, 1} with `channel` ∈ {true, false} and `squash: 1, hissLevelDB: -20`, a 3 s render is finite with a peak ≤ 0.95 (the −1 dBFS ceiling is about 0.891, plus tolerance).
  - `NightFactoryTests.factoryIsDeterministic`: the same request renders the same array.
  - `NightFactoryTests.channelOffIsBrighter`: the centroid of `channel: false` is greater than the centroid of `channel: true`, for the waves.
  - `NightCtlTests.parsesARequest`: `NightCtl.Audition.parse(["chimes","--seconds","30","--distance","0.5","--no-channel","--seed","9"]).request()` equals `AuditionRequest(scene: .chimes, seconds: 30, seed: 9, warp: WarpDepth(distance: 0.5), channel: false)`.
  - `NightCtlTests.rejectsBadInput`: parsing `["bells"]`, `["chimes","--distance","1.5"]` and `["chimes","--seconds","-1"]` each throws.
  - `NightCtlTests.badInputWritesNothing`: running the command via `NightCtl.parseAsRoot(["audition","chimes","--distance","2","--out",tmp])` throws, and no file exists at `tmp`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement `NightFactory` and `NightCLI`.**
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS.
- [ ] **Step 5: Run the tool end to end**: `cd swift && swift run nightctl audition waves --seconds 20 --distance 0.6 --out "$TMPDIR/w.wav"`. Expected: exit 0 and the file exists, about 3.5 MB (20 s × 44100 × 4 bytes).
- [ ] **Step 6: Commit** `git commit -m "feat(swift): one factory, and nightctl to audition a scene"`

---

### Task 8: The listening set, and the docs

**Files:**
- Create: `swift/README.md`
- Modify: `docs/project-state.md` (top section "Where the project is heading"), `docs/architecture.md` (new section), `README.md` (a short pointer to `swift/`)

- [ ] **Step 1: Render the listening set** into `swift/listening/` (git-ignored by the existing `*.wav` rule). Use seed 1, 60 s each, all with the channel:
  - `chimes` and `waves`, at warp plain;
  - `--distance 0.5 --slowness 0.5`;
  - `--distance 1 --slowness 1 --fragmentation 0.6 --proportion 0.8`;
  - plain with `--no-channel`.

  That's eight files. Add `swift/listening/render.sh`, which regenerates them with `swift run nightctl`.
- [ ] **Step 2: Measure.** `render.sh` keeps each `nightctl` line it prints (RMS, peak and centroid). Put those eight lines, as a table, in project-state.
- [ ] **Step 3: Write the docs.**
  - **`swift/README.md`:** how to build, test, audition, and the target layout rule (`NightPlan` is pure).
  - **`docs/architecture.md`:** a section "The Swift engine (Plan 7a)" covering the target split and why, seekability (the fixed grid, the hashed noise, the exact versus pre-roll seek), the chain order, and the single factory.
  - **`docs/project-state.md`:** what 7a shipped, test count, the measurement table, and **every placeholder by name and value**. That includes the chime grid and probabilities, partial ratios and decays, the strike attack, the waves grid and lengths, the pixellation rate and bits, the distance mapping, the fragment cell and fade, every channel constant, the master ceiling, and the 2 s glides. It also records that the listening judgement is outstanding.
- [ ] **Step 4: Run** `cd swift && swift test -c release`. Expected: all PASS. Record the count.
- [ ] **Step 5: Commit** `git commit -m "docs: Plan 7a — the Swift engine, a listening set, and its placeholders"`
- [ ] **Step 6: Hand the listening set to the operator.** List the eight files and the one command to regenerate or vary them (`swift run nightctl audition <scene> … --play`). The milestone is done when they've listened, not when the tests pass.
