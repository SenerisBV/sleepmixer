import Foundation
import NightPlan

/// Felted rain as heard on a window pane close by: many soft drops with no hard transients, over a
/// soft low-passed wash, the whole thing swelling very slowly. Mono, dry, unit gain; the window
/// treatment and the stereo pairing live elsewhere.
///
/// Seekable by construction (the chimes' way). Drops live on a fixed grid of cells keyed by absolute
/// frame; each drop is a Hann-windowed sine burst (so its attack is half its length, at least 3 ms)
/// whose parameters are a pure function of (seed, cell). The wash is hash noise keyed by absolute
/// frame through a lowpass, so a render started at any second matches a continuous one once the
/// lowpass state (a few milliseconds) has settled.
public struct RainSound: SoundSource {
    // MARK: - Values from the plan (placeholders recorded in docs/project-state.md)

    static let dropRateRange = 40.0...120.0      // drops per second, wandering slowly inside this
    static let dropAttackMinSeconds = 0.003      // a drop's raised-cosine attack is never shorter
    static let washCutoffHz = 3000.0
    static let swellPeriodRange = 20.0...60.0    // seconds
    static let swellDepthDB = 3.0                // +/- dB on drops and wash together

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let dropLengthRange = 0.012...0.030   // seconds; the Hann window's attack is half of this
    static let dropHzRange = 500.0...2200.0      // log-uniform pitch
    static let dropLevelRange = 0.3...1.0
    static let dropGain = 0.07
    static let washGain = 0.2
    /// The wash is gently rounded (tanh) at about 2.5 sigma so its rare noise peaks stay soft.
    static let washSoftClip = 0.55
    static let washHighpassHz = 150.0            // keeps the wash from thumping
    static let rateWanderPeriodRange = 25.0...70.0
    // NightRandom streams (seed-level streams 0-4, per-cell streams 6-11; 5 unused).
    static let swellPeriodStream: UInt64 = 0
    static let swellPhaseStream: UInt64 = 1
    static let ratePeriodStream: UInt64 = 2
    static let ratePhaseStream: UInt64 = 3
    static let washStream: UInt64 = 4
    static let presenceStream: UInt64 = 6
    static let jitterStream: UInt64 = 7
    static let lengthStream: UInt64 = 8
    static let pitchStream: UInt64 = 9
    static let levelStream: UInt64 = 10
    static let phaseStream: UInt64 = 11

    // MARK: - State

    private struct Drop {
        var cell = -1
        var start = 0              // absolute frame
        var length = 0
        var omega = 0.0
        var phase = 0.0
        var amp = 0.0
    }

    private static let slotCount = 8     // >= ceil((longest drop + one cell) / cell) + 1
    private let seed: UInt64
    private let sr: Double
    private let cellFrames: Int
    private let swellOmega: Double, swellPhase: Double
    private let rateOmega: Double, ratePhase: Double
    /// Test hook: 0 renders the drops alone (to check their attacks without the wash).
    var washLevel = 1.0
    private var frame: Int
    private var slots = [Drop](repeating: Drop(), count: RainSound.slotCount)
    private var loadedCell: Int
    private var wash: Biquad
    private var washHP: Biquad

    public init(seed: UInt64, sampleRate: Double, startSecond: Double) {
        self.seed = seed
        sr = sampleRate
        cellFrames = max(1, Int((sampleRate / RainSound.dropRateRange.upperBound).rounded()))
        func period(_ r: ClosedRange<Double>, _ stream: UInt64) -> Double {
            r.lowerBound + (r.upperBound - r.lowerBound) * NightRandom.unit(seed, stream, 0)
        }
        swellOmega = 2 * Double.pi / period(RainSound.swellPeriodRange, RainSound.swellPeriodStream)
        swellPhase = 2 * Double.pi * NightRandom.unit(seed, RainSound.swellPhaseStream, 0)
        rateOmega = 2 * Double.pi / period(RainSound.rateWanderPeriodRange, RainSound.ratePeriodStream)
        ratePhase = 2 * Double.pi * NightRandom.unit(seed, RainSound.ratePhaseStream, 0)
        frame = max(0, Int((startSecond * sampleRate).rounded()))
        wash = Biquad.lowpass(cutoff: RainSound.washCutoffHz, sampleRate: sampleRate)
        washHP = Biquad.highpass(cutoff: RainSound.washHighpassHz, sampleRate: sampleRate)
        loadedCell = frame / cellFrames - RainSound.slotCount
        // Cold start: drops already falling at `startSecond` are part of the sound.
        loadThrough(frame / cellFrames)
    }

    private mutating func loadThrough(_ cell: Int) {
        while loadedCell < cell {
            loadedCell += 1
            if loadedCell >= 0 { slots[loadedCell % RainSound.slotCount] = drop(cell: loadedCell) }
        }
    }

    /// The drop born in `cell`, or an empty one: presence follows the wandering rate.
    private func drop(cell: Int) -> Drop {
        let cellSecond = Double(cell * cellFrames) / sr
        let r = RainSound.dropRateRange
        let rate = (r.lowerBound + r.upperBound) / 2
            + (r.upperBound - r.lowerBound) / 2 * sin(rateOmega * cellSecond + ratePhase)
        let c = UInt64(cell)
        guard NightRandom.unit(seed, RainSound.presenceStream, c) < rate / r.upperBound else {
            return Drop(cell: cell)
        }
        let lr = RainSound.dropLengthRange
        let length = Int(((lr.lowerBound + (lr.upperBound - lr.lowerBound)
                           * NightRandom.unit(seed, RainSound.lengthStream, c)) * sr).rounded())
        let pr = RainSound.dropHzRange
        let hz = pr.lowerBound * pow(pr.upperBound / pr.lowerBound, NightRandom.unit(seed, RainSound.pitchStream, c))
        let lv = RainSound.dropLevelRange
        return Drop(
            cell: cell,
            start: cell * cellFrames + Int(NightRandom.unit(seed, RainSound.jitterStream, c) * Double(cellFrames)),
            length: length,
            omega: 2 * Double.pi * hz / sr,
            phase: 2 * Double.pi * NightRandom.unit(seed, RainSound.phaseStream, c),
            amp: RainSound.dropGain * (lv.lowerBound + (lv.upperBound - lv.lowerBound)
                                        * NightRandom.unit(seed, RainSound.levelStream, c)))
    }

    public mutating func render(into out: inout [Float], count: Int) {
        let swellDB = RainSound.swellDepthDB
        for i in 0..<count {
            let f = frame
            loadThrough(f / cellFrames)
            var x = 0.0
            for k in 0..<RainSound.slotCount {
                let d = slots[k]
                let age = f - d.start
                guard d.length > 0, age >= 0, age < d.length else { continue }
                let w = 0.5 * (1 - cos(2 * Double.pi * Double(age) / Double(d.length)))
                x += d.amp * w * sin(d.omega * Double(age) + d.phase)
            }
            let n = Float(NightRandom.signed(seed, RainSound.washStream, UInt64(f)))
            let y = Double(washHP.process(wash.process(n)))
            x += washLevel * RainSound.washGain * RainSound.washSoftClip * tanh(y / RainSound.washSoftClip)
            let t = Double(f) / sr
            x *= pow(10, swellDB * sin(swellOmega * t + swellPhase) / 20)
            out[i] = Float(x)
            frame += 1
        }
    }
}
