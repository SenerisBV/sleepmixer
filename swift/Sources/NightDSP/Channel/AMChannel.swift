import Foundation
import NightPlan

/// The AM channel every source is heard through: hiss and crackle, night fading, a narrow band,
/// then squash and warmth. Warmth is `tanh(drive*x)/drive`: unity gain for quiet signals, so squash
/// rounds peaks but never raises the level (the spec's ratchet: overall level only goes down).
///
/// Settings are read every 512 frames (on the absolute-frame grid) and glided with a one-pole
/// smoother over 2 s; gains and rates move per sample between block values, filter coefficients
/// per block. Hiss and crackle are pure functions of the absolute frame. The fade's smooth noise
/// runs on an integrated phase, so a rate change never jumps it; a processor started at `T`
/// begins that phase at `rate(T) * T`, which equals the continuous phase when the rate has been
/// constant. Filters and the compressor are stateful, so a seek is approximate: start a few
/// seconds early and discard the lead-in (the factory's job).
public struct AMChannel: Processor {
    // Brief values (placeholders recorded in Task 8)
    static let blockFrames = 512
    static let glideSeconds = 2.0
    static let hissCornerHz = 6000.0
    static let grainsPerSecond = 40.0
    static let grainMinSeconds = 0.003
    static let grainMaxSeconds = 0.008
    static let grainLevelSpanDB = 6.0          // grain level drawn from crackle - 6 ... crackle
    static let fadeStream: UInt64 = 31
    static let selectiveStream: UInt64 = 32
    static let selectiveCutDB = -9.0
    static let selectiveLowHz = 600.0
    static let selectiveHighHz = 2500.0
    static let attackSeconds = 0.05
    static let releaseSeconds = 0.4
    static let thresholdDB = -24.0

    // Invented
    static let hissStream: UInt64 = 33
    static let grainOffsetStream: UInt64 = 34
    static let grainLengthStream: UInt64 = 35
    static let grainLevelStream: UInt64 = 36
    static let grainNoiseStream: UInt64 = 37
    static let selectiveQ = 1.0
    static let butterworthQ = 0.7071
    static let fourthOrderQs = (0.5412, 1.3066)   // Butterworth 4th order as two biquads
    /// Equivalent noise bandwidth of a 2nd-order Butterworth lowpass, as a multiple of its corner.
    static let noiseBandwidthFactor = (Double.pi / 4) / sin(Double.pi / 4)

    /// The settings that glide, as plain numbers (already clamped by `ChannelSettings`).
    struct Params {
        var low, high, hissDB, crackleDB, fadeDepth, fadeRate, squash: Double
        init(_ s: ChannelSettings) {
            low = s.lowCornerHz; high = s.highCornerHz; hissDB = s.hissLevelDB
            crackleDB = s.crackleLevelDB; fadeDepth = s.fadeDepth; fadeRate = s.fadeRateHz; squash = s.squash
        }
        func toward(_ t: Params, _ a: Double) -> Params {
            var p = self
            p.low += a * (t.low - low); p.high += a * (t.high - high)
            p.hissDB += a * (t.hissDB - hissDB); p.crackleDB += a * (t.crackleDB - crackleDB)
            p.fadeDepth += a * (t.fadeDepth - fadeDepth); p.fadeRate += a * (t.fadeRate - fadeRate)
            p.squash += a * (t.squash - squash)
            return p
        }
    }

    private let sampleRate: Double
    private let seed: UInt64
    private let settings: Curve<ChannelSettings>
    private let startFrame: Int
    private let glideCoefficient: Double
    private let hissNormal: Double
    private let attackCoefficient: Double
    private let releaseCoefficient: Double
    private var frame: Int
    private var prev: Params
    private var cur: Params
    /// Smooth-noise phase: knots of `s(t)` sit at integer phases. Advances by fadeRateHz / sr per frame.
    private(set) var fadePhase: Double
    private var hissFilter: Biquad
    private var selective: Biquad
    private var highpass: Biquad
    private var lowpassA: Biquad
    private var lowpassB: Biquad
    private var meanSquare = 0.0

    public init(sampleRate: Double, seed: UInt64, settings: Curve<ChannelSettings>, startSecond: Double) {
        self.sampleRate = sampleRate
        self.seed = seed
        self.settings = settings
        let start = startSecond.isFinite ? max(0, startSecond) : 0
        startFrame = Int((start * sampleRate).rounded())
        frame = startFrame
        glideCoefficient = 1 - exp(-Double(Self.blockFrames) / (Self.glideSeconds * sampleRate))
        // Scales uniform noise (RMS 1/sqrt 3) so the lowpassed hiss has RMS 1 (times the level).
        let passFraction = min(Self.noiseBandwidthFactor * Self.hissCornerHz / (sampleRate / 2), 1)
        hissNormal = 3.0.squareRoot() / passFraction.squareRoot()
        attackCoefficient = exp(-1 / (Self.attackSeconds * sampleRate))
        releaseCoefficient = exp(-1 / (Self.releaseSeconds * sampleRate))
        let p = Params(settings(Double(startFrame) / sampleRate))
        prev = p
        cur = p
        fadePhase = p.fadeRate * Double(startFrame) / sampleRate
        hissFilter = Biquad.lowpass(cutoff: Self.hissCornerHz, q: Self.butterworthQ, sampleRate: sampleRate)
        selective = Biquad.peaking(center: 1000, q: Self.selectiveQ, gainDB: 0, sampleRate: sampleRate)
        highpass = Biquad.highpass(cutoff: p.low, q: Self.butterworthQ, sampleRate: sampleRate)
        lowpassA = Biquad.lowpass(cutoff: p.high, q: Self.fourthOrderQs.0, sampleRate: sampleRate)
        lowpassB = Biquad.lowpass(cutoff: p.high, q: Self.fourthOrderQs.1, sampleRate: sampleRate)
        retune(p)
    }

    // MARK: - Pure functions of the frame

    /// Smooth noise in 0...1: cosine interpolation between `unit(seed, stream, k)` knots at integer phases.
    static func smooth(seed: UInt64, stream: UInt64, phase: Double) -> Double {
        let k = phase.rounded(.down)
        let a = NightRandom.unit(seed, stream, UInt64(max(k, 0)))
        let b = NightRandom.unit(seed, stream, UInt64(max(k, 0) + 1))
        return a + (b - a) * Envelope.raisedCosine(phase - k)
    }

    /// The crackle grain envelope at `frame`, relative to crackleLevelDB: the grain's level offset
    /// (−6...0 dB) times a full Hann window, 0 between grains. One grain per 1/40 s slot, placed
    /// wholly inside it, so grains never overlap and the envelope never exceeds 1 by construction.
    static func grainShape(seed: UInt64, frame: Int, sampleRate: Double) -> Double {
        let t = Double(frame) / sampleRate
        let slot = (t * grainsPerSecond).rounded(.down)
        let k = UInt64(max(slot, 0))
        let length = grainMinSeconds + (grainMaxSeconds - grainMinSeconds) * NightRandom.unit(seed, grainLengthStream, k)
        let slack = 1 / grainsPerSecond - length
        let start = slot / grainsPerSecond + slack * NightRandom.unit(seed, grainOffsetStream, k)
        let p = (t - start) / length
        guard p > 0 && p < 1 else { return 0 }
        let offsetDB = -grainLevelSpanDB * NightRandom.unit(seed, grainLevelStream, k)
        let hann = 0.5 - 0.5 * cos(2 * Double.pi * p)
        return pow(10, offsetDB / 20) * hann
    }

    // MARK: - Processing

    private mutating func retune(_ p: Params) {
        let s2 = Self.smooth(seed: seed, stream: Self.selectiveStream, phase: fadePhase)
        let center = Self.selectiveLowHz * pow(Self.selectiveHighHz / Self.selectiveLowHz, s2)
        let cut = Self.selectiveCutDB * p.fadeDepth * s2
        selective.setCoefficients(from: Biquad.peaking(center: center, q: Self.selectiveQ, gainDB: cut, sampleRate: sampleRate))
        highpass.setCoefficients(from: Biquad.highpass(cutoff: p.low, q: Self.butterworthQ, sampleRate: sampleRate))
        lowpassA.setCoefficients(from: Biquad.lowpass(cutoff: p.high, q: Self.fourthOrderQs.0, sampleRate: sampleRate))
        lowpassB.setCoefficients(from: Biquad.lowpass(cutoff: p.high, q: Self.fourthOrderQs.1, sampleRate: sampleRate))
    }

    public mutating func process(_ buffer: inout [Float], count: Int) {
        for i in 0..<count {
            if frame % Self.blockFrames == 0 && frame > startFrame {
                prev = cur
                cur = cur.toward(Params(settings(Double(frame) / sampleRate)), glideCoefficient)
                retune(cur)
            }
            let u = Double(frame % Self.blockFrames) / Double(Self.blockFrames)
            func lerp(_ a: Double, _ b: Double) -> Double { a + (b - a) * u }

            // 1. Hiss and crackle.
            let hissAmp = pow(10, lerp(prev.hissDB, cur.hissDB) / 20) * hissNormal
            let hiss = Double(hissFilter.process(Float(hissAmp * NightRandom.signed(seed, Self.hissStream, UInt64(frame)))))
            var crackle = 0.0
            let shape = Self.grainShape(seed: seed, frame: frame, sampleRate: sampleRate)
            if shape > 0 {
                crackle = pow(10, lerp(prev.crackleDB, cur.crackleDB) / 20) * shape
                    * NightRandom.signed(seed, Self.grainNoiseStream, UInt64(frame))
            }
            var x = Double(buffer[i]) + hiss + crackle

            // 2. Night fading (the selective part is the peaking filter, retuned per block).
            let s = Self.smooth(seed: seed, stream: Self.fadeStream, phase: fadePhase)
            x *= 1 - lerp(prev.fadeDepth, cur.fadeDepth) * s
            fadePhase += lerp(prev.fadeRate, cur.fadeRate) / sampleRate
            var y = selective.process(Float(x))

            // 3. Band.
            y = lowpassB.process(lowpassA.process(highpass.process(y)))

            // 4. Squash (RMS compressor) and warmth.
            let v = Double(y)
            let squared = v * v
            let c = squared > meanSquare ? attackCoefficient : releaseCoefficient
            meanSquare = squared + c * (meanSquare - squared)
            let squash = lerp(prev.squash, cur.squash)
            let ratio = 1 + 3 * squash
            let over = 10 * log10(meanSquare + 1e-30) - Self.thresholdDB
            let gain = over > 0 ? pow(10, -over * (1 - 1 / ratio) / 20) : 1
            let drive = 1 + 2 * squash
            // Warmth has unity gain when quiet (tanh(d*x)/d ~ x), so squash only ever rounds peaks and
            // never raises the level: the spec's ratchet says overall level only goes down across the
            // night, and a planner raising squash must not make the night louder.
            let warm = tanh(drive * v * gain) / drive
            // Safety floor: |tanh(d*x)/d| < 1/d <= 1 already; kept against future edits.
            buffer[i] = Float(min(max(warm, -1), 1))
            frame += 1
        }
    }
}
