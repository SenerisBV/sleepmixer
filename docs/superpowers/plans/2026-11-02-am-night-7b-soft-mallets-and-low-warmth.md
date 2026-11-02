# Plan 7b: soft mallets and low warmth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chimes become soft-mallet bars with three dials the night will turn (ring length, softness of the start, vibrato), and a new "low warmth" scene joins the library. Both are auditionable with `nightctl`.

**Architecture:** Plan 7a's Swift package at `swift/`, unchanged in shape. `WarpDepth` (in `NightPlan`) gains three tone dials that scenes without notes ignore. `ChimesScene` keeps its seekable fixed grid, slowness rules and lookback, but its voice recipe is replaced. `LowWarmthScene` is a new `Scene`, synthesized additively so that seeks are exact. A small shared helper makes proportion power-preserving for both. The factory and CLI gain the new scene and dials.

**Tech Stack:** Swift 6.4, SwiftPM, Swift Testing, swift-argument-parser 1.5.0, as in 7a.

**Spec:** `docs/superpowers/specs/2026-11-02-am-night-design.md`. Read the section "What listening taught: soft mallets, not bells (2026-11-02)" under "The scenes"; it is the authority for this plan. Also read `docs/project-state.md`, section "Before the planner moves anything" (level neutrality, I1).

## Global Constraints

- Everything in Plan 7a's Global Constraints still holds (`docs/superpowers/plans/2026-11-02-am-night-7a-two-scenes-through-the-channel.md`):
  - `NightPlan` is pure and Foundation-only.
  - Mono `Float`, with the sample rate passed in.
  - No transients.
  - One factory.
  - All randomness comes from `NightRandom`.
  - Seeking is the factory's job.
  - No agent has ears: listening samples are written and measured, never judged.
  - Tests run with `swift test -c release`.
  - Every invented number is recorded in `docs/project-state.md`.
- **The spec's sound, verbatim:**
  - "a near-pure fundamental, a faint overtone two octaves up (×4, about −24 dB) and a fainter one at ×10 (about −36 dB), each overtone dying faster than the fundamental as on a real bar";
  - "no mallet noise at all";
  - "a raised-cosine soft start";
  - "High notes are allowed."
- **Dials:**
  - **Ring:** the ring time constant goes from 1.4 s at ring 0 to 4.2 s at ring 1. The spike measured 1.4 s as close to the reference and 2.8 s as sleepier; 4.2 is a placeholder ceiling.
  - **Softness:** the attack goes from 0.035 s at softness 0 to 0.12 s at softness 1. The spike measured 35 ms and 80 ms; 0.12 is a placeholder ceiling.
  - **Vibrato:** an amplitude pulse at 4.5 Hz, depth `0.18 × vibrato`.
  - All three are frozen per note at its birth.
- **Level neutrality** (spec: the dials "obey the same rules … a longer ring must not make the scene louder overall"):
  - neither ring nor vibrato may change a scene's long-run RMS by more than ±1 dB;
  - proportion is power-preserving in the new and rebuilt scenes.
- **Low warmth** (spec): "slow low chords, a slightly detuned pair per note, lowpassed around 380 Hz, swelling in over seconds".
- The waves are untouched.

## Review Focus

1. **The highest notes at maximum proportion** favouring an overtone (×10 at +6 dB) must still not read as metallic. Test in Task 2: energy above 2 kHz stays under 1% for the top note of the range at every proportion.
2. **Ring 1 + softness 1 + slowness 1 together:** the longest, softest, sparsest notes must neither overlap into a loudness build-up nor blow the peak. Test in Task 2: an analytic peak bound over the worst case.
3. **Seeking into a long ring:** a note born before the seek point must still be heard correctly after it. Task 2's exact-seek test runs at ring 1.
4. **48 kHz:** dial times are in seconds, and the warmth's lowpass is in Hz. Tests at 48000 in Tasks 2 and 3.
5. **CLI dial input past the edges** (`--ring 1.5`, `--vibrato=nan`): a clear "must be" error and nothing written. Test in Task 1.

---

### Task 1: Three tone dials in `WarpDepth`, the factory and the CLI

**Files:**
- Modify: `swift/Sources/NightPlan/WarpDepth.swift`
- Modify: `swift/Sources/NightCLI/NightCtl.swift`
- Modify: `swift/Tests/NightPlanTests/NightPlanTests.swift`
- Modify: `swift/Tests/NightCLITests/NightCtlTests.swift`

**Interfaces:**
- Produces: `WarpDepth` gains `public var ring: Double`, `softness: Double` and `vibrato: Double`. Each is clamped to 0…1, with NaN becoming 0, exactly like the existing four. The memberwise `init` gains `ring: Double = 0, softness: Double = 0, vibrato: Double = 0` after `proportion`. Existing call sites stay valid. The doc comment says these are tone dials that scenes without notes ignore.
- Produces: `nightctl audition` gains `--ring`, `--softness` and `--vibrato` (Double, default 0), validated like the other depths and mapped in `request()`.

- [ ] **Step 1: Write the failing tests.**
  - `NightPlanTests.toneDialsClamp`: `WarpDepth(ring: 1.5, softness: -1, vibrato: .nan)` gives `ring == 1, softness == 0, vibrato == 0`. Setting each through its setter clamps too.
  - `NightCtlTests.parsesToneDials`: `["chimes","--ring","0.5","--softness","1","--vibrato","0.25"]` gives `request().warp == WarpDepth(ring: 0.5, softness: 1, vibrato: 0.25)`.
  - Extend `validateNamesTheField` with `--ring=1.5`, `--softness=-0.1` and `--vibrato=nan`.
- [ ] **Step 2: Run** `cd swift && swift test -c release --filter "NightPlanTests|NightCtlTests"`. Expected: FAIL to compile.
- [ ] **Step 3: Implement** the three fields, flags and validation.
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS, with the 7a tests unchanged.
- [ ] **Step 5: Commit** `feat(swift): ring, softness and vibrato dials`.

---

### Task 2: Soft-mallet chimes

**Files:**
- Modify (rewrite the voice recipe): `swift/Sources/NightDSP/Scenes/ChimesScene.swift`
- Modify: `swift/Sources/NightDSP/Scenes/Proportion.swift`
- Modify (rewrite): `swift/Tests/NightDSPTests/ChimesSceneTests.swift`

**Interfaces:**
- Consumes: Task 1's `WarpDepth.ring/softness/vibrato`, plus `Envelope`, `NightRandom` and `Analysis`.
- Produces:
  - `Proportion.powerPreservingGains(seed: UInt64, stream: UInt64, index: UInt64, baseAmps: [Double], proportion: Double) -> [Double]`. It returns linear gains, applied on top of `baseAmps`, that are the existing `gainsDB` shape (one favoured +6p dB, the rest −12p dB) rescaled so that `Σ (base_i · g_i)²` equals `Σ base_i²`. The waves keep using `gainsDB` unchanged (I1 is the planner's job).
  - `ChimesScene` with `elements == ["fundamental", "fourth", "tenth"]`.
  - Test-visible statics:
    - `ringSeconds(_ ring: Double) -> Double` (1.4…4.2, linear);
    - `attackSeconds(_ softness: Double) -> Double` (0.035…0.12, linear);
    - `vibratoDepth(_ v: Double) -> Double` (`0.18·v`);
    - `static let vibratoHz = 4.5`;
    - the existing `fundamental(seed:cell:warp:)`, `strikeTimes(...)` and `elementGains(...)`;
    - `static func peakBound() -> Double` (Step 3).

**What stays from 7a, unchanged:**
- the 2.2 s grid and offsets;
- density `0.6/(1+2·slowness)`;
- the root and pentatonic range;
- the 3-semitone slowness pitch drop;
- warp frozen at birth;
- the 60 s lookback;
- the 256-frame absolute block grid;
- Double time from absolute frames;
- the fixed sum order.

**What goes:** the strike and mallet noise, the bloom, the beating, the bell ratios, and **the slowness decay stretch** (ring owns ring time now).

**The voice:**
- Partials at ×1, ×4 and ×10, with base amplitudes `[1, 10^(−24/20), 10^(−36/20)]`. The partial at ×k decays with time constant `τ / sqrt(k)`, where `τ = ringSeconds(ring)`.
- Partials above 0.45·sampleRate are skipped.
- Each note's onset is `Envelope.raisedCosine(t / attackSeconds(softness))`.
- **Vibrato.** The multiplier is `1 − d·(0.5 − 0.5·cos(2π·4.5·t + φ))`, where `d = vibratoDepth(vibrato)` and `φ = 2π·unit(seed, 6, cell)`. Divide it by its mean, `1 − d/2`, so that vibrato is level-neutral.
- **Ring level-neutrality.** Scale each note by `sqrt(1.4 / τ)`, so its energy, which is proportional to τ, is constant across ring.
- **Life.** A note ends at the earlier of `7·τ` and the existing 58 s cap, with the existing 4 s / quarter fade to true zero.
- **Level.** Pick `masterGain` so a plain passage peaks near −6 dBFS, as in 7a. Document the measured value.

- [ ] **Step 1: Write the failing tests.** Replace the old bell-specific tests: `strikeAttackIsSoft`, `nothingAbove6k` as written, and the bell `proportionReweights`. Keep and port `sameSeedSameSound`, `seekIsExact`, `seekIsExactLateAndChunked` (now at `ring: 1, slowness: 1`), `hourEightIsHealthy`, `slownessThinsAndLowers` (density and centroid only), `slownessLowersPitchByThreeSemitones` and `listeningSample`. New tests:
  - **`elementsAreNamed`:** the three names above.
  - **`partialsAreAPureBar`:** render one isolated note via a test-visible single-note renderer, `static func renderNote(f: Double, warp: WarpDepth, seconds: Double, sampleRate: Double) -> [Float]`, which uses the same voice code as the scene. Measure 50–350 ms after onset with a Hann FFT. Expect peaks at exactly ×4 and ×10 (within one bin) and −24 ± 2 dB and −36 ± 3 dB below the fundamental. Expect nothing within −50 dB at the old bell ratios ×2, ×2.76 or ×4.07.
  - **`noMalletTing`:** the first 15 ms of a note has under 0.5% of its energy above 2 kHz, at the scene's highest possible fundamental (top root × top pentatonic degree). Do this at 44100 and 48000.
  - **`softnessSetsTheAttack`:** the 10%→90% rise of `renderNote`'s envelope is ≥ 0.6 × `attackSeconds` at softness 0 and at softness 1. `attackSeconds(1) / attackSeconds(0) > 3`.
  - **`ringSetsTheDecay`:** the −20 dB time of `renderNote`'s fundamental is about `τ·ln(10)` (±10%) at ring 0, 0.5 and 1.
  - **`ringIsLevelNeutral`** and **`vibratoIsLevelNeutral`:** 600 s renders over seeds 1…5 at the dial at 0 and 1. The mean RMS differs by ≤ 1 dB.
  - **`vibratoPulsesAt4_5Hz`:** at vibrato 1, the envelope (50 ms RMS hop) of a 6 s isolated note, detrended by its exponential, has its strongest modulation component within 4.5 ± 0.3 Hz. At vibrato 0, there is no component above −40 dB relative.
  - **`proportionPreservesPower`:** `powerPreservingGains` satisfies the power identity to 1e-9 for proportion 0, 0.5 and 1. At proportion 1, exactly one element is favoured.
  - **`highNotesStayRound`** (Review Focus 1): at the highest fundamental, proportion 1 with each element favoured in turn, `Analysis.bandEnergyRatio(above: 2000) < 0.01` on a `renderNote` render.
  - **`peakIsBounded`** (Review Focus 2): `peakBound()` is the analytic worst case at ring 1, softness 0, slowness 0 and proportion 1. It sums, over earlier cells k = 0, 1, 2, …, the maximum single-note amplitude times `exp(−k·2.2/τ_max)` (every cell occupied, which is conservative). Assert `peakBound() ≤ 0.9`. Separately, a 600 s render at those settings, at 44100 and 48000, peaks ≤ `peakBound()`. Mutation-check the bound by doubling `masterGain`.
- [ ] **Step 2: Run** `swift test -c release --filter ChimesSceneTests`. Expected: FAIL.
- [ ] **Step 3: Implement** the voice recipe, `powerPreservingGains` and the test-visible statics.
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS. Do one mutation check per new test: remove the ×4 partial, add back a 1 ms attack, drop the `sqrt(1.4/τ)` scaling, drop the vibrato mean-correction, use `gainsDB` instead of power-preserving gains. List them in the report.
- [ ] **Step 5: Write listening samples** with `NIGHT_LISTEN_DIR` (60 s each): `chimes-soft-plain`, `chimes-soft-ring`, `chimes-soft-softness`, `chimes-soft-vibrato`, and `chimes-soft-all` (all three dials at 1). Report the paths and their RMS, peak and centroid. Don't judge them.
- [ ] **Step 6: Commit** `feat(swift): soft-mallet chimes with ring, softness and vibrato`.

---

### Task 3: The low-warmth scene

**Files:**
- Create: `swift/Sources/NightDSP/Scenes/LowWarmthScene.swift`
- Create: `swift/Tests/NightDSPTests/LowWarmthSceneTests.swift`
- Modify: `swift/Sources/NightPlan/SceneKind.swift` (add `case warmth`)
- Modify: `swift/Sources/NightDSP/NightFactory.swift` (add the switch arm)
- Modify: `swift/Sources/NightCLI/NightCtl.swift` (help text lists `warmth`)

**Interfaces:**
- Consumes: `Scene`, `NightRandom`, `Proportion.powerPreservingGains`, `WarpDepth`, `Analysis`.
- Produces:
  - `public struct LowWarmthScene: Scene` with `kind == .warmth` and `elements == ["root", "fifth", "third"]`.
  - Test-visible:
    - `static func chord(seed: UInt64, cell: Int, warp: WarpDepth) -> [Double]` (the three fundamentals in Hz);
    - `static let cellSeconds = 12.0`;
    - `static let swellSeconds = 3.0`;
    - `static let cutoffHz = 380.0`;
    - `static func peakBound() -> Double`.

**The recipe:**
- **Chords.** A chord is born every 12 s cell (no gaps). It is drawn by `unit(seed, 41, cell)` from the diatonic triads of a per-seed root: `unit(seed, 40, 0)` picks the root from MIDI 29–36 (F1–C2), and the triads are I, vi, IV and V in root position, voiced root, fifth, third an octave up. Each chord lives 12 + 2·3 = 18 s: a 3 s raised-cosine swell in, a sustain, a 3 s swell out. Consecutive chords therefore crossfade over 3 s on each side.
- **Slowness** lengthens the cell up to ×2. Like the chimes, it does this with a fixed 12 s grid in which cell `i` holds a new chord when `unit(seed, 42, i) < 1/(1+slowness)`, and otherwise the previous chord's life extends by one cell. That stays a pure function of the cell index.
- **Proportion** reweights root, fifth and third through `powerPreservingGains`.
- **Each note** is two detuned voices (±5 cents) with a slow drift: cosine interpolation of `signed(seed, 43…, k)` knots every 10 s, ±4 cents.
- **Each voice** is an *additive* band-limited saw, harmonics k = 1… while `k·f < 0.45·sr`, amplitude `1/k`. Each harmonic is multiplied by a 4-pole Butterworth lowpass magnitude at 380 Hz, `1/sqrt(1 + (k·f/380)^8)`. Harmonics below −60 dB are skipped.
- **Seeking.** All phases come from absolute Double time since the chord's birth, so seeking is **exact**.
- **Level.** `masterGain` comes from `peakBound()` (the sum of the worst-case partial amplitudes of two overlapping chords), with the bound ≤ 0.9, as with the waves.

- [ ] **Step 1: Write the failing tests.**
  - `sameSeedSameSound`
  - `seekIsExact`: start at 47 s against continuous, compared with `==`.
  - `hourEightIsHealthy`
  - **`staysLow`:** `Analysis.bandEnergyRatio(above: 500) < 0.05` at 44100 and 48000. Its centroid is within 10% between the two rates.
  - **`swellIsSmooth`:** the largest frame-to-frame change in the summed chord envelope is ≤ the raised-cosine bound `π/(2·3·sr)·1.01` per chord.
  - **`neverSilentNeverStacked`:** over 1200 s, at every frame, between 1 and 2 chords are sounding, so it never drops out and never stacks three.
  - **`slownessLengthensChords`:** the mean chord life at slowness 1 is ≥ 1.6× the mean at 0, over 3600 s and seeds 1…5.
  - **`chordsAreDiatonic`:** every chord from `chord(...)` over 500 cells is one of I, vi, IV or V of the seed's root.
  - **`proportionIsLevelNeutral`:** 600 s RMS at proportion 0 and at proportion 1 is within ±1 dB.
  - **`peakIsBounded`:** `peakBound() ≤ 0.9`, and a 600 s render at proportion 1 peaks ≤ the bound. Mutation-check it.
  - **`listeningSample`:** `warmth-plain`.
  - Factory: in `NightFactoryTests`, extend the scene list in `everyCornerIsSafe` and `seekingMatchesALongerRender` to include `.warmth`.
  - CLI: `parsesARequest` with `"warmth"`.
- [ ] **Step 2: Run** `swift test -c release --filter "LowWarmthSceneTests|NightFactoryTests|NightCtlTests"`. Expected: FAIL.
- [ ] **Step 3: Implement** the recipe.
- [ ] **Step 4: Run** `swift test -c release`. Expected: all PASS. Do one mutation check per new test, and list them.
- [ ] **Step 5: Commit** `feat(swift): the low-warmth scene`.

---

### Task 4: The listening set and the docs

**Files:**
- Modify: `swift/listening/render.sh`
- Modify: `docs/project-state.md`
- Modify: `docs/architecture.md`
- Modify: `swift/README.md`

- [ ] **Step 1: Extend `render.sh`** to also render, at seed 1 and 60 s each, with the channel on:
  - `chimes-soft-plain`;
  - `chimes-soft-sleepy` (`--ring 1 --softness 1`);
  - `chimes-soft-deep` (`--ring 1 --softness 1 --vibrato 1 --distance 0.6 --slowness 0.5`);
  - `chimes-soft-nochannel`;
  - `warmth-plain`;
  - `warmth-nochannel`.
  Keep the existing waves renders. Remove the old `chimes-*` renders: those bells no longer exist. Run it, and keep `measurements.txt`.
- [ ] **Step 2: Update `docs/project-state.md`.** Add a "Plan 7b: soft mallets and low warmth" section after Plan 7a's. Cover:
  - **The reason, in the operator's words:** the listening rounds, the station-chime quote and the felted reference. Point to the spec section; don't duplicate it.
  - **What shipped,** the test count and the measurement table.
  - **Every new placeholder by name and value,** verified against the code: dial ranges, overtone levels, vibrato rate and depth, the warmth cell, swell, cutoff, chord set, root range, detune and drift, and both master gains.
  - **What was removed** (the bell recipe and its constants), so the 7a placeholder list isn't misread.
  - **That the 7a chimes measurements no longer describe the current chimes.**
  - **That the waves still use non-power-preserving proportion** (I1 stands for them).
  - **That the channel's settings were tuned against the old bells** and await re-listening with the new chimes.
- [ ] **Step 3: Update `docs/architecture.md`.** In the Swift engine section, describe the tone dials, power-preserving proportion, and the warmth scene's additive-and-analytic-lowpass approach. Explain why: that approach gives exact seeks, which a stateful filter wouldn't.
- [ ] **Step 4: Update `swift/README.md`** with the new scene and flags.
- [ ] **Step 5: Run** `swift test -c release`, record the count, and commit `docs: Plan 7b — soft mallets, low warmth, their placeholders`.
- [ ] **Step 6: Hand the listening set to the operator.** Give the paths and one command to vary them. The milestone is done when they've listened.
