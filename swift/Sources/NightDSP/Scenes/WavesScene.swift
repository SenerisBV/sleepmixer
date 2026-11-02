import Foundation
import NightPlan

/// Pixellated waves: surf built from one stream of hashed noise, cut into a low swell, a mid
/// break and a high hiss of the wash, then rendered at low resolution (sample rate and bit
/// depth stepped down) so it reads as *remembered* surf.
///
/// Waves are born on a fixed grid. Each wave freezes the warp at its birth and runs its own
/// three filters from that birth, fed noise keyed by absolute frame, so every wave's signal is
/// a pure function of the absolute frame. The sample-and-hold is keyed to absolute frames too.
/// The one piece of state that crosses waves is the 4 kHz output lowpass, so a seek is close
/// to a continuous render rather than exact; the factory's 6 s lead-in settles it.
public struct WavesScene: Scene {
    public static let kind = SceneKind.waves
    public let elements = ["swell", "break", "wash"]

    // MARK: - Values from the brief (placeholders recorded in Task 8)

    static let gridSeconds = 6.0
    static let density = 0.85
    static let baseLength = 7.0
    static let lengthRange = 5.0
    static let existStream: UInt64 = 11
    static let lengthStream: UInt64 = 12
    static let noiseStream: UInt64 = 13
    static let swellCutoff = 400.0
    static let swellRise = 0.45            // fraction of the wave's length
    static let breakBand = 800.0...2500.0
    static let breakPeak = 0.55
    static let washCutoff = 1500.0
    static let washStart = 0.5             // the tail fills the last 50%
    static let holdHz = 5512.0
    static let holdSlowDrop = 0.4          // hold rate × (1 − 0.4 × slowness)
    static let bits = 7
    static let outputCutoff = 4000.0

    // MARK: - Invented values (placeholders recorded in Task 8)

    static let favouredStream: UInt64 = 14
    static let breakRiseFrom = 0.30        // break rises from 30% to its 55% peak...
    static let breakFallTo = 0.85          // ...and falls to zero at 85%
    static let washAttack = 0.05           // wash rises over 5% of the length from its start,
    static let washDecay = 0.15            // decays with a time constant of 15% of the length,
    static let washFade = 0.10             // and fades to true zero over the last 10%
    static let elementLevels = [1.0, 0.6, 0.35]  // swell, break, wash, before proportion
    static let noiseRMS = 0.25             // each filtered noise is scaled to this RMS
    static let masterGain = 0.2            // slowness 1 + proportion 1 peaks near -2 dBFS (worst of 20 seeds)
    static let warpBlockFrames = 256       // the hold rate reads the warp once per absolute block
    static let impulseFrames = 16_384      // to measure each band's noise gain
    static var maxLength: Double { (baseLength + lengthRange) * 2 }

    // MARK: - The grid (pure, shared by the renderer and the tests)

    /// Birth second, length and the warp frozen at birth, or nil when the grid slot is empty.
    private static func wave(seed: UInt64, index: Int, warp: Curve<WarpDepth>) -> (birth: Double, length: Double, warp: WarpDepth)? {
        guard index >= 0 else { return nil }
        let birth = Double(index) * gridSeconds
        let w = warp(birth)
        guard NightRandom.unit(seed, existStream, UInt64(index)) < density / (1 + w.slowness) else { return nil }
        let length = (baseLength + NightRandom.unit(seed, lengthStream, UInt64(index)) * lengthRange) * (1 + w.slowness)
        return (birth, length, w)
    }

    /// Spans of the waves born in `[from, to)`.
    static func waveSpans(seed: UInt64, warp: Curve<WarpDepth>, from: Double, to: Double) -> [ClosedRange<Double>] {
        let first = max(0, Int((from / gridSeconds).rounded(.up)))
        let last = Int((to / gridSeconds).rounded(.up)) - 1
        guard first <= last else { return [] }
        return (first...last).compactMap { i in
            wave(seed: seed, index: i, warp: warp).map { $0.birth...($0.birth + $0.length) }
        }
    }

    /// Linear per-element amplitudes, in `elements` order: level × proportion × master.
    private static func weights(seed: UInt64, index: Int, proportion: Double) -> [Double] {
        let dB = Proportion.gainsDB(seed: seed, stream: favouredStream, index: UInt64(index), count: 3, proportion: proportion)
        return (0..<3).map { elementLevels[$0] * pow(10, dB[$0] / 20) * masterGain }
    }

    /// Element `e`'s shape at `t` seconds into a wave of `length` seconds; zero at both ends.
    static func shape(_ e: Int, t: Double, length: Double) -> Double {
        guard t > 0, t < length else { return 0 }
        let u = t / length
        switch e {
        case 0:
            return u < swellRise
                ? Envelope.raisedCosine(u / swellRise)
                : 1 - Envelope.raisedCosine((u - swellRise) / (1 - swellRise))
        case 1:
            return u < breakPeak
                ? Envelope.raisedCosine((u - breakRiseFrom) / (breakPeak - breakRiseFrom))
                : 1 - Envelope.raisedCosine((u - breakPeak) / (breakFallTo - breakPeak))
        default:
            let tail = Envelope.attackDecay(t: u - washStart, attack: washAttack, decay: washDecay)
            return tail * (1 - Envelope.raisedCosine((u - (1 - washFade)) / washFade))
        }
    }

    /// The mid-tread 7-bit quantiser: input clamped to ±1, 127 levels, 0 stays 0.
    static func quantise(_ x: Double) -> Float {
        let steps = Double((1 << (bits - 1)) - 1)
        return Float((min(max(x, -1), 1) * steps).rounded() / steps)
    }

    private static func frame(_ second: Double, _ sr: Double) -> Int { Int((second * sr).rounded()) }

    /// The summed wave envelope (every element's shape × amplitude), the same sum the renderer
    /// normalises by. Pure in (seed, warp, second).
    public func envelope(at second: Double) -> Double {
        let first = max(0, Int(((second - Self.maxLength) / Self.gridSeconds).rounded(.down)))
        let last = Int((second / Self.gridSeconds).rounded(.down))
        guard first <= last else { return 0 }
        var sum = 0.0
        for i in first...last {
            guard let w = Self.wave(seed: seed, index: i, warp: warp) else { continue }
            let a = Self.weights(seed: seed, index: i, proportion: w.warp.proportion)
            for e in 0..<3 { sum += a[e] * Self.shape(e, t: second - w.birth, length: w.length) }
        }
        return sum
    }

    // MARK: - Voices

    private struct Wave {
        var birth: Int               // absolute frame
        var end: Int                 // first absolute frame with no sound
        var length: Double           // seconds
        var amps: [Double]
        var filters: [Biquad]        // zeroed at birth
        var next: Int                // next absolute frame the filters will take
    }

    /// Off only in tests, to hear (measure) the scene without its low resolution.
    var pixellate = true

    private let seed: UInt64
    private let sr: Double
    private let warp: Curve<WarpDepth>
    private let bandGains: [Double]
    private var position: Int
    private var nextIndex: Int
    private var waves: [Wave] = []
    private var output: Biquad
    private var holdRate = 0.0
    private var warpBlock = Int.min
    private var holdIndex = Int.min
    private var held: Float = 0

    public init(seed: UInt64, sampleRate: Double, warp: Curve<WarpDepth>, startSecond: Double) {
        self.seed = seed
        self.sr = sampleRate
        self.warp = warp
        let start = startSecond.isFinite ? max(0, startSecond) : 0
        position = Self.frame(start, sampleRate)
        // Every wave born up to the longest length before the start may still be sounding.
        nextIndex = max(0, Int(((start - Self.maxLength) / Self.gridSeconds).rounded(.down)))
        output = Biquad.lowpass(cutoff: Self.outputCutoff, sampleRate: sampleRate)
        // Scale each band so uniform ±1 noise through it comes out at `noiseRMS`.
        bandGains = Self.filters(sampleRate).map { proto in
            var f = proto
            var energy = 0.0
            for k in 0..<Self.impulseFrames {
                let h = Double(f.process(k == 0 ? 1 : 0))
                energy += h * h
            }
            return Self.noiseRMS / ((energy / 3).squareRoot())
        }
    }

    private static func filters(_ sr: Double) -> [Biquad] {
        let lo = breakBand.lowerBound, hi = breakBand.upperBound
        let centre = (lo * hi).squareRoot()
        return [
            .lowpass(cutoff: swellCutoff, sampleRate: sr),
            .bandpass(center: centre, q: centre / (hi - lo), sampleRate: sr),
            .highpass(cutoff: washCutoff, sampleRate: sr),
        ]
    }

    private func noise(_ f: Int) -> Float {
        Float(NightRandom.signed(seed, Self.noiseStream, UInt64(f)))
    }

    private func makeWave(index: Int, at f: Int) -> Wave? {
        guard let w = Self.wave(seed: seed, index: index, warp: warp) else { return nil }
        let birth = Self.frame(w.birth, sr)
        var wave = Wave(birth: birth, end: birth + Self.frame(w.length, sr), length: w.length,
                        amps: Self.weights(seed: seed, index: index, proportion: w.warp.proportion),
                        filters: Self.filters(sr), next: birth)
        guard wave.end > f else { return nil }
        // A wave already under way (after a seek) runs its filters from its own birth.
        while wave.next < f {
            let n = noise(wave.next)
            for e in 0..<3 { _ = wave.filters[e].process(n) }
            wave.next += 1
        }
        return wave
    }

    private mutating func sample(_ f: Int) -> Float {
        if f / Self.warpBlockFrames != warpBlock {
            warpBlock = f / Self.warpBlockFrames
            let slow = warp(Double(warpBlock * Self.warpBlockFrames) / sr).slowness
            holdRate = Self.holdHz * (1 - Self.holdSlowDrop * slow)
        }
        while Self.frame(Double(nextIndex) * Self.gridSeconds, sr) <= f {
            if let w = makeWave(index: nextIndex, at: f) { waves.append(w) }
            nextIndex += 1
        }
        waves.removeAll { $0.end <= f }

        let n = noise(f)
        var x = 0.0, env = 0.0
        for i in waves.indices {
            let t = Double(f - waves[i].birth) / sr
            for e in 0..<3 {
                let y = Double(waves[i].filters[e].process(n))
                let a = waves[i].amps[e] * Self.shape(e, t: t, length: waves[i].length)
                env += a
                x += a * bandGains[e] * y
            }
            waves[i].next = f + 1
        }

        var y = x
        if pixellate {
            let h = Int((Double(f) * holdRate / sr).rounded(.down))
            if h != holdIndex {
                holdIndex = h
                held = Self.quantise(env > 0 ? x / env : 0)
            }
            y = Double(held) * env
        }
        return output.process(Float(y))
    }

    public mutating func render(into out: inout [Float], count: Int) {
        for i in 0..<count {
            out[i] = sample(position)
            position += 1
        }
    }
}
