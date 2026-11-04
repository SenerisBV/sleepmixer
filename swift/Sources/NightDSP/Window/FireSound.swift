import Foundation
import NightPlan

/// A fire heard through a window: a steady soft crackle with an occasional low pop. Mono, dry, unit
/// gain; the window treatment and the stereo pairing live elsewhere (the fire skips the treatment).
///
/// The crackle is sparse 2-10 ms bursts of noise in 1-4 kHz, each under a Hann window (attack half
/// its length, so at least 1 ms), over a faint low bed. It is steady: it does not read `sudden`.
/// The pops are rarer, louder, lower, longer bursts (still Hann-felted). A pop is a "sudden" sound:
/// it reads `sudden` once, at its start second, and is born only if a hashed unit is under its base
/// chance (1 at full rate) times `rateScale`; its gain is `gainDB`. With `rateScale == 0` there are
/// no pops, ever, and only the steady crackle is left.
///
/// Seekable by construction (the rain's way). Crackle bursts live on a grid of 1/15 s cells keyed by
/// absolute frame, with a presence chance that follows a slowly wandering rate (3-15 per second).
/// Pops live on a grid of 35 s cells, each holding at most one pop starting in its first 25 s, so
/// neighbouring pops are 10...60 s apart at full rate; a pop (under 50 ms) never leaves its cell.
/// All noise is hash noise keyed by absolute frame through filters that settle in milliseconds.
public struct FireSound: SoundSource {
    // MARK: - Values from the plan (placeholders recorded in docs/project-state.md)

    static let burstLengthRange = 0.002...0.010  // seconds; the Hann window's attack is half of this
    static let burstAttackMinSeconds = 0.001
    static let crackleBand = 1000.0...4000.0     // Hz
    static let crackleRateRange = 3.0...15.0     // bursts per second, wandering slowly inside this
    static let popGapRange = 10.0...60.0         // seconds between pops at full rate (via the grid below)

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let rateWanderPeriodRange = 8.0...25.0
    static let burstLevelRange = 0.7...1.0
    static let crackleGain = 0.10
    static let crackleNorm = 15.0                // drives the band-passed noise well into the soft clip, so its peaks are flat
    static let softClip = 0.55                   // tanh rounding, so rare noise peaks stay soft
    static let bedHz = 400.0                     // the faint low bed: lowpassed noise
    static let bedGain = 0.012
    static let bedNorm = 8.0
    static let popCellSeconds = 35.0             // with popOffsetSeconds, gives gaps of 10...60 s
    static let popOffsetSeconds = 25.0
    static let popBaseChance = 1.0
    static let popLengthRange = 0.020...0.050    // seconds; attack 10-25 ms
    static let popBand = 150.0...900.0           // Hz
    static let popLevelRange = 0.6...1.0
    static let popGain = 0.22
    static let popNorm = 6.0
    // NightRandom streams: 100-101 noise, 102-103 seed-level wander, 104-108 per crackle cell,
    // 109-113 per pop cell.
    static let crackleNoiseStream: UInt64 = 100
    static let popNoiseStream: UInt64 = 101
    static let bedNoiseStream: UInt64 = 102
    static let wanderPeriodStream: UInt64 = 103
    static let wanderPhaseStream: UInt64 = 114
    static let presenceStream: UInt64 = 104
    static let jitterStream: UInt64 = 105
    static let lengthStream: UInt64 = 106
    static let levelStream: UInt64 = 107
    static let popOffsetStream: UInt64 = 109
    static let popBirthStream: UInt64 = 110
    static let popLengthStream: UInt64 = 111
    static let popLevelStream: UInt64 = 112

    // MARK: - State

    private struct Burst {
        var cell = -1
        var start = -1             // absolute frame, or -1 for none
        var length = 0
        var amp = 0.0
    }

    private static let slotCount = 3     // a burst (<= 10 ms) spans at most two 1/15 s cells
    private let seed: UInt64
    private let sr: Double
    private let sudden: Curve<Sudden>
    private let cellFrames: Int
    private let popCellFrames: Int
    private let wanderOmega: Double, wanderPhase: Double
    /// Test hook: renders only the burst and pop envelopes (constant carrier, no bed), to check
    /// their attacks without the noise hiding them.
    var envelopeOnly = false
    private var frame: Int
    private var slots = [Burst](repeating: Burst(), count: FireSound.slotCount)
    private var loadedCell: Int
    private var pop = Burst()
    private var crackleBand1: Biquad, crackleBand2: Biquad, crackleBand3: Biquad
    private var crackleSmooth: Biquad
    private var popBand1: Biquad, popBand2: Biquad
    private var bed: Biquad

    public init(seed: UInt64, sampleRate: Double, startSecond: Double, sudden: Curve<Sudden>) {
        self.seed = seed
        sr = sampleRate
        self.sudden = sudden
        cellFrames = max(1, Int((sampleRate / FireSound.crackleRateRange.upperBound).rounded()))
        popCellFrames = Int((FireSound.popCellSeconds * sampleRate).rounded())
        let wr = FireSound.rateWanderPeriodRange
        wanderOmega = 2 * Double.pi / (wr.lowerBound + (wr.upperBound - wr.lowerBound)
                                        * NightRandom.unit(seed, FireSound.wanderPeriodStream, 0))
        wanderPhase = 2 * Double.pi * NightRandom.unit(seed, FireSound.wanderPhaseStream, 0)
        frame = max(0, Int((startSecond * sampleRate).rounded()))
        crackleBand1 = Biquad.highpass(cutoff: FireSound.crackleBand.lowerBound, sampleRate: sampleRate)
        crackleBand2 = Biquad.lowpass(cutoff: FireSound.crackleBand.upperBound, sampleRate: sampleRate)
        crackleBand3 = Biquad.lowpass(cutoff: FireSound.crackleBand.upperBound, sampleRate: sampleRate)
        crackleSmooth = Biquad.lowpass(cutoff: FireSound.crackleBand.upperBound, sampleRate: sampleRate)
        popBand1 = Biquad.highpass(cutoff: FireSound.popBand.lowerBound, sampleRate: sampleRate)
        popBand2 = Biquad.lowpass(cutoff: FireSound.popBand.upperBound, sampleRate: sampleRate)
        bed = Biquad.lowpass(cutoff: FireSound.bedHz, sampleRate: sampleRate)
        loadedCell = frame / cellFrames - FireSound.slotCount
        loadThrough(frame / cellFrames)
        pop = makePop(cell: frame / popCellFrames)
    }

    private mutating func loadThrough(_ cell: Int) {
        while loadedCell < cell {
            loadedCell += 1
            if loadedCell >= 0 { slots[loadedCell % FireSound.slotCount] = burst(cell: loadedCell) }
        }
    }

    /// The crackle burst of `cell`, or an empty one: presence follows the wandering rate.
    private func burst(cell: Int) -> Burst {
        let cellSecond = Double(cell * cellFrames) / sr
        let r = FireSound.crackleRateRange
        let rate = (r.lowerBound + r.upperBound) / 2
            + (r.upperBound - r.lowerBound) / 2 * sin(wanderOmega * cellSecond + wanderPhase)
        let c = UInt64(cell)
        guard NightRandom.unit(seed, FireSound.presenceStream, c) < rate / r.upperBound else { return Burst(cell: cell) }
        let lr = FireSound.burstLengthRange
        let lv = FireSound.burstLevelRange
        return Burst(
            cell: cell,
            start: cell * cellFrames + Int(NightRandom.unit(seed, FireSound.jitterStream, c) * Double(cellFrames)),
            length: Int(((lr.lowerBound + (lr.upperBound - lr.lowerBound)
                          * NightRandom.unit(seed, FireSound.lengthStream, c)) * sr).rounded()),
            amp: FireSound.crackleGain * (lv.lowerBound + (lv.upperBound - lv.lowerBound)
                                           * NightRandom.unit(seed, FireSound.levelStream, c)))
    }

    /// The pop of `cell`, or an empty one when none is born there.
    private func makePop(cell: Int) -> Burst {
        let c = UInt64(cell)
        let startSecond = Double(cell) * FireSound.popCellSeconds
            + FireSound.popOffsetSeconds * NightRandom.unit(seed, FireSound.popOffsetStream, c)
        let s = sudden(startSecond)
        guard NightRandom.unit(seed, FireSound.popBirthStream, c) < FireSound.popBaseChance * s.rateScale else {
            return Burst(cell: cell)
        }
        let lr = FireSound.popLengthRange
        let lv = FireSound.popLevelRange
        return Burst(
            cell: cell,
            start: Int((startSecond * sr).rounded()),
            length: Int(((lr.lowerBound + (lr.upperBound - lr.lowerBound)
                          * NightRandom.unit(seed, FireSound.popLengthStream, c)) * sr).rounded()),
            amp: FireSound.popGain * pow(10, s.gainDB / 20)
                * (lv.lowerBound + (lv.upperBound - lv.lowerBound) * NightRandom.unit(seed, FireSound.popLevelStream, c)))
    }

    private static func hann(_ b: Burst, at f: Int) -> Double {
        let age = f - b.start
        guard b.start >= 0, age >= 0, age < b.length else { return 0 }
        return b.amp * 0.5 * (1 - cos(2 * Double.pi * Double(age) / Double(b.length)))
    }

    public mutating func render(into out: inout [Float], count: Int) {
        let clip = FireSound.softClip
        for i in 0..<count {
            let f = frame
            loadThrough(f / cellFrames)
            if f / popCellFrames != pop.cell { pop = makePop(cell: f / popCellFrames) }
            let cn = Float(NightRandom.signed(seed, FireSound.crackleNoiseStream, UInt64(f)))
            let c = Double(crackleBand3.process(crackleBand2.process(crackleBand1.process(cn)))) * FireSound.crackleNorm
            let pn = Float(NightRandom.signed(seed, FireSound.popNoiseStream, UInt64(f)))
            let p = Double(popBand2.process(popBand1.process(pn))) * FireSound.popNorm
            let bn = Float(NightRandom.signed(seed, FireSound.bedNoiseStream, UInt64(f)))
            let b = Double(bed.process(bn)) * FireSound.bedNorm
            var x = FireSound.hann(pop, at: f) * (envelopeOnly ? 1 : clip * tanh(p / clip))
            var env = 0.0
            for k in 0..<FireSound.slotCount { env += FireSound.hann(slots[k], at: f) }
            if envelopeOnly {
                x += env
            } else {
                x += env * Double(crackleSmooth.process(Float(clip * tanh(c / clip))))
                x += FireSound.bedGain * clip * tanh(b / clip)
            }
            out[i] = Float(x)
            frame += 1
        }
    }
}
