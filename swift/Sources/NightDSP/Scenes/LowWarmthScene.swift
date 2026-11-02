import Foundation
import NightPlan

/// Low warmth: slow low chords, a slightly detuned pair per note, lowpassed around 380 Hz,
/// swelling in over seconds. The warm low end the operator loves in *Everything In Its Right
/// Place* ("very soothing and warm and feels like something from childhood"), as a scene of its
/// own that the night can bring in and out.
///
/// A chord is born on a fixed 12 s grid: the diatonic triads I, vi, IV and V of a per-seed root
/// (MIDI 29–36), in root position, voiced root, fifth, and the third an octave up. A chord that
/// occupies cells i…j sounds from `12i − 3` to `12(j+1) + 3` s, with a 3 s raised-cosine swell at
/// each end, so consecutive chords overlap for 6 s: the next swells in while the previous still
/// sustains, then the previous swells out. Slowness lets a chord hold for more cells.
///
/// Each note is two voices detuned ±5 cents, each drifting slowly by up to ±4 cents. Each voice is
/// an *additive* band-limited saw whose harmonics are weighted by a 4-pole Butterworth magnitude
/// at 380 Hz, `1/sqrt(1 + (f/380)^8)`. Additive, not a filter, on purpose (the waves document the
/// other side of this trade-off): a stateful filter would carry history across a seek, while an
/// analytic magnitude keeps every sample a pure function of the absolute frame.
///
/// Seekable exactly. Each voice's phase is a closed form of the Double time since its chord's
/// birth (the drift's integral is closed-form too); every block of 256 absolute frames starts
/// from that exact phase and advances linearly to the exact phase at the block's end. Chords are
/// summed in birth order, then note, voice and harmonic, so a render started at any second is
/// bit-identical to the same frames of a continuous render.
public struct LowWarmthScene: Scene {
    public static let kind = SceneKind.warmth
    public let elements = ["root", "fifth", "third"]

    // MARK: - Values from the brief (placeholders recorded in docs/project-state.md)

    static let cellSeconds = 12.0
    static let swellSeconds = 3.0
    static let cutoffHz = 380.0
    static let rootMIDIRange = 29...36                 // F1…C2
    /// I, vi, IV, V: (semitones above the root, the chord's third in semitones).
    static let triads: [(degree: Int, third: Int)] = [(0, 4), (9, 3), (5, 4), (7, 4)]
    static let detuneCents = 5.0                        // the pair sits at ±5 cents
    static let driftCents = 4.0                         // each voice drifts within ±4 cents...
    static let driftKnotSeconds = 10.0                  // ...through cosine-interpolated knots every 10 s
    static let harmonicCeiling = 0.45                   // harmonics stay below 0.45 × sample rate
    static let skipBelow = 1e-3                         // harmonics under -60 dB are skipped
    static let rootStream: UInt64 = 40
    static let chordStream: UInt64 = 41
    static let birthStream: UInt64 = 42
    static let driftStream: UInt64 = 43

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    /// Proportion's favoured note per chord (the brief reserved 40–43; this is the next stream).
    static let favouredStream: UInt64 = 44
    /// The drift knot index packs (birth cell, voice, knot) into one stream-43 index, so every
    /// voice of every chord drifts independently: cell << 32 | voice << 24 | knot.
    static let blockFrames = 256          // each block restarts the phases on this absolute-frame grid
    /// Also invented, and stated where they live: every voice starts at phase 0 (a sine-phase saw)
    /// at its chord's birth; harmonic amplitudes are fixed at birth from the voice's detuned
    /// frequency (the ±4 cent drift moves pitch, not the lowpass weighting); the drift's frequency
    /// ratio is linearised (see `Voice.phase`); before its birth a voice's drift integral extends
    /// linearly from the first knot (only reached under a zero envelope); a chord may repeat the
    /// previous one (each cell draws from all four triads).
    /// The -60 dB skip is relative to an unfiltered fundamental (amplitude 1). Proportion's power
    /// is preserved over each note's RMS (both voices' harmonics), not over equal weights, so a
    /// favoured low root is not louder than a favoured high third.
    /// Derived from `peakBound()`: with masterGain 1 the worst chord's summed partial amplitudes
    /// are 14.86, and two overlapping chords 29.72. Bound ≤ 0.9 needs masterGain ≤ 0.03028;
    /// 0.03 gives a bound of 0.892 (-1.0 dBFS). `peakIsBounded` re-checks this. The bound takes
    /// every partial at its crest at once, so real peaks sit far below it (about -10 dBFS).
    static let masterGain = 0.03

    // MARK: - Chords (pure, shared by the renderer and the tests)

    static func rootMIDI(seed: UInt64) -> Int {
        let n = rootMIDIRange.count
        return rootMIDIRange.lowerBound + min(Int(NightRandom.unit(seed, rootStream, 0) * Double(n)), n - 1)
    }

    private static func hz(midi: Int) -> Double { 440 * pow(2, Double(midi - 69) / 12) }

    private static func triad(root: Int, _ t: (degree: Int, third: Int)) -> [Double] {
        let r = root + t.degree
        return [hz(midi: r), hz(midi: r + 7), hz(midi: r + t.third + 12)]
    }

    /// The three fundamentals in Hz (root, fifth, third an octave up) of the chord born in `cell`.
    /// `warp` is the warp it froze at birth; no warp dial changes the pitch today.
    static func chord(seed: UInt64, cell: Int, warp: WarpDepth) -> [Double] {
        let i = min(Int(NightRandom.unit(seed, chordStream, UInt64(max(0, cell))) * 4), 3)
        return triad(root: rootMIDI(seed: seed), triads[i])
    }

    /// Whether a new chord is born in `cell` (cell 0 always holds one).
    private static func isBirth(seed: UInt64, cell: Int, warp: Curve<WarpDepth>) -> Bool {
        guard cell > 0 else { return cell == 0 }
        let w = warp(Double(cell) * cellSeconds)
        return NightRandom.unit(seed, birthStream, UInt64(cell)) < 1 / (1 + w.slowness)
    }

    /// The birth cell of the chord sounding through `cell`.
    private static func birthCell(seed: UInt64, containing cell: Int, warp: Curve<WarpDepth>) -> Int {
        var c = max(0, cell)
        while !isBirth(seed: seed, cell: c, warp: warp) { c -= 1 }
        return c
    }

    /// One chord's life: born in `birthCell`, sounding over `start…end` seconds, with the warp it froze.
    struct Span {
        var birthCell: Int
        var start: Double
        var end: Double
        var warp: WarpDepth
    }

    private static func span(seed: UInt64, birthCell i: Int, warp: Curve<WarpDepth>) -> Span {
        var next = i + 1
        while !isBirth(seed: seed, cell: next, warp: warp) { next += 1 }
        return Span(birthCell: i,
                    start: Double(i) * cellSeconds - swellSeconds,
                    end: Double(next) * cellSeconds + swellSeconds,
                    warp: warp(Double(i) * cellSeconds))
    }

    /// The chords that sound at some point in `(from, to)`, in birth order.
    static func chordSpans(seed: UInt64, warp: Curve<WarpDepth>, from: Double, to: Double) -> [Span] {
        var cell = birthCell(seed: seed, containing: Int((from / cellSeconds).rounded(.down)) - 1, warp: warp)
        var out: [Span] = []
        while Double(cell) * cellSeconds - swellSeconds < to {
            if isBirth(seed: seed, cell: cell, warp: warp) {
                let s = span(seed: seed, birthCell: cell, warp: warp)
                if s.end > from { out.append(s) }
            }
            cell += 1
        }
        return out
    }

    /// One chord's envelope at second `t`: a raised-cosine swell in over its first 3 s and out
    /// over its last 3 s, 1 between, 0 outside. The renderer uses this per frame.
    static func envelope(_ s: Span, at t: Double) -> Double {
        guard t > s.start, t < s.end else { return 0 }
        var e = 1.0
        if t < s.start + swellSeconds { e *= Envelope.raisedCosine((t - s.start) / swellSeconds) }
        if t > s.end - swellSeconds { e *= 1 - Envelope.raisedCosine((t - (s.end - swellSeconds)) / swellSeconds) }
        return e
    }

    // MARK: - The voice's spectrum

    /// The 4-pole Butterworth lowpass magnitude at `hz`.
    static func lowpass(_ hz: Double) -> Double { 1 / (1 + pow(hz / cutoffHz, 8)).squareRoot() }

    /// Harmonic amplitudes of one voice at fundamental `f`: `1/k` times the lowpass, while
    /// `k·f < 0.45·sr` and the amplitude is at least -60 dB (both factors fall with k, so the first
    /// harmonic under -60 dB ends the series).
    static func harmonicAmps(f: Double, sampleRate: Double) -> [Double] {
        var amps: [Double] = []
        var k = 1
        while Double(k) * f < harmonicCeiling * sampleRate {
            let a = lowpass(Double(k) * f) / Double(k)
            if a < skipBelow { break }
            amps.append(a)
            k += 1
        }
        return amps
    }

    /// The pair's frequencies for a note at `f`: -5 and +5 cents.
    static func pair(_ f: Double) -> [Double] {
        [f * pow(2, -detuneCents / 1200), f * pow(2, detuneCents / 1200)]
    }

    /// Per-note harmonic amplitudes (both voices) and the gains proportion applies on top.
    private static func noteAmps(_ freqs: [Double], sampleRate: Double) -> [[[Double]]] {
        freqs.map { f in pair(f).map { harmonicAmps(f: $0, sampleRate: sampleRate) } }
    }

    private static func noteRMS(_ amps: [[[Double]]]) -> [Double] {
        amps.map { $0.joined().map { $0 * $0 }.reduce(0, +).squareRoot() }
    }

    // MARK: - Peak bound

    /// The analytic worst-case peak: two chords at full envelope (consecutive chords overlap, and
    /// while one swells the other is at most 1), each at the largest sum of its partial
    /// amplitudes over every root, triad, favoured note and proportion (0…1 in steps of 0.01),
    /// times masterGain. Every partial is taken at its crest at once.
    public static func peakBound() -> Double {
        var worst = 0.0
        for root in rootMIDIRange {
            for t in triads {
                let amps = noteAmps(triad(root: root, t), sampleRate: .infinity)
                let sums = amps.map { $0.joined().reduce(0, +) }
                let base = noteRMS(amps)
                for fav in 0..<3 {
                    for step in 0...100 {
                        let g = Proportion.powerPreservingGains(favoured: fav, baseAmps: base, proportion: Double(step) / 100)
                        worst = max(worst, zip(sums, g).map { $0 * $1 }.reduce(0, +))
                    }
                }
            }
        }
        return 2 * worst * masterGain
    }

    // MARK: - Voices

    private struct Voice {
        var f: Double
        var amps: [Double]            // final: harmonic × proportion gain × masterGain
        var knots: [Double]           // drift in cents at every 10 s from birth
        var integral: [Double]        // ∫ drift over [0, 10k] s, in cent-seconds

        init(f: Double, amps: [Double], knots: [Double]) {
            self.f = f
            self.amps = amps
            self.knots = knots
            var acc = 0.0
            integral = [0]
            for m in 0..<(knots.count - 1) {
                acc += LowWarmthScene.driftKnotSeconds * (knots[m] + knots[m + 1]) / 2
                integral.append(acc)
            }
        }

        /// The phase in radians `tau` seconds after the chord's birth. The drift multiplies the
        /// frequency by `1 + κ·cents` (κ = ln 2 / 1200), linearised from `2^(cents/1200)`: off by
        /// under 0.001 cent at ±4 cents, and its integral is closed-form.
        func phase(_ tau: Double) -> Double {
            let kappa = M_LN2 / 1200
            let span = LowWarmthScene.driftKnotSeconds
            let drift: Double        // ∫ cents dt from birth, in cent-seconds
            if tau <= 0 {
                drift = knots[0] * tau
            } else {
                let k = min(Int(tau / span), knots.count - 2)
                let u = (tau - Double(k) * span) / span
                let a = knots[k], b = knots[k + 1]
                drift = integral[k] + span * (a * u + (b - a) / 2 * (u - sin(Double.pi * u) / Double.pi))
            }
            return 2 * Double.pi * f * (tau + kappa * drift)
        }
    }

    private struct Chord {
        var span: Span
        var voices: [Voice]

        init(seed: UInt64, span: Span, sr: Double) {
            self.span = span
            let freqs = LowWarmthScene.chord(seed: seed, cell: span.birthCell, warp: span.warp)
            let amps = LowWarmthScene.noteAmps(freqs, sampleRate: sr)
            let g = Proportion.powerPreservingGains(seed: seed, stream: LowWarmthScene.favouredStream,
                                                    index: UInt64(span.birthCell),
                                                    baseAmps: LowWarmthScene.noteRMS(amps),
                                                    proportion: span.warp.proportion)
            let knotCount = Int(((span.end - span.start) / LowWarmthScene.driftKnotSeconds).rounded(.up)) + 2
            voices = []
            for (n, f) in freqs.enumerated() {
                for (p, fv) in LowWarmthScene.pair(f).enumerated() {
                    let v = UInt64(2 * n + p)
                    let knots = (0..<knotCount).map { k in
                        LowWarmthScene.driftCents * NightRandom.signed(
                            seed, LowWarmthScene.driftStream, UInt64(span.birthCell) << 32 | v << 24 | UInt64(k))
                    }
                    voices.append(Voice(f: fv, amps: amps[n][p].map { $0 * g[n] * LowWarmthScene.masterGain }, knots: knots))
                }
            }
        }

        /// Adds this chord's frames in `[b, b + block.count)` into `block`; `env` is scratch.
        /// Each voice's phase starts at its exact value at frame `b` and steps linearly to its
        /// exact value at the block's end, so the result depends only on `b`.
        func render(into block: inout [Double], env: inout [Double], from b: Int, sr: Double) {
            let n = block.count
            let t0 = Double(b) / sr, t1 = Double(b + n) / sr
            guard span.start < t1, span.end > t0 else { return }
            for j in 0..<n { env[j] = LowWarmthScene.envelope(span, at: Double(b + j) / sr) }
            for v in voices {
                let p0 = v.phase(t0 - span.start), p1 = v.phase(t1 - span.start)
                let step = (p1 - p0) / Double(n)
                let cd = cos(step), sd = sin(step)
                var c = cos(p0), s = sin(p0)
                v.amps.withUnsafeBufferPointer { a in
                    for j in 0..<n {
                        // sin(kφ) by the Chebyshev recurrence: s_k = 2cos(φ)·s_{k-1} - s_{k-2}.
                        let twoC = 2 * c
                        var prev = 0.0, cur = s, x = 0.0
                        for k in 0..<a.count {
                            x += a[k] * cur
                            let next = twoC * cur - prev
                            prev = cur
                            cur = next
                        }
                        block[j] += x * env[j]
                        let c2 = c * cd - s * sd
                        s = s * cd + c * sd
                        c = c2
                    }
                }
            }
        }
    }

    private let seed: UInt64
    private let sr: Double
    private let warp: Curve<WarpDepth>
    private var position: Int
    private var nextCell: Int
    private var chords: [Chord] = []
    private var block: [Double]
    private var env: [Double]
    private var blockStart = Int.min

    public init(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, startSecond: Double) {
        self.seed = seed
        self.sr = sampleRate
        self.warp = warp
        let start = startSecond.isFinite ? max(0, startSecond) : 0
        position = Int((start * sampleRate).rounded())
        // Lookback: the chord sounding a cell before the start is the earliest that can still be
        // heard (any earlier chord ended at least 9 s before the start).
        nextCell = Self.birthCell(seed: seed, containing: Int((start / Self.cellSeconds).rounded(.down)) - 1, warp: warp)
        block = [Double](repeating: 0, count: Self.blockFrames)
        env = block
    }

    /// Renders the absolute block starting at `b` (a multiple of `blockFrames`) into `block`.
    private mutating func renderBlock(_ b: Int) {
        let t0 = Double(b) / sr, t1 = Double(b + Self.blockFrames) / sr
        chords.removeAll { $0.span.end <= t0 }
        while Double(nextCell) * Self.cellSeconds - Self.swellSeconds < t1 {
            if Self.isBirth(seed: seed, cell: nextCell, warp: warp) {
                chords.append(Chord(seed: seed, span: Self.span(seed: seed, birthCell: nextCell, warp: warp), sr: sr))
            }
            nextCell += 1
        }
        for i in 0..<Self.blockFrames { block[i] = 0 }
        for c in chords { c.render(into: &block, env: &env, from: b, sr: sr) }
        blockStart = b
    }

    public mutating func render(into out: inout [Float], count: Int) {
        var written = 0
        while written < count {
            let b = (position / Self.blockFrames) * Self.blockFrames
            if b != blockStart { renderBlock(b) }
            let take = min(b + Self.blockFrames - position, count - written)
            for i in 0..<take { out[written + i] = Float(block[position - b + i]) }
            written += take
            position += take
        }
    }
}
