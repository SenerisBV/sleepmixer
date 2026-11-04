import Foundation
import NightPlan

/// Distant thunder heard through a window: slow low rolls, never a close crack. Each roll is a
/// rumble of low-passed noise, pixellated the way `WavesScene` is (sample-and-hold at a reduced
/// rate, bit reduction, then a gentle lowpass), under a slow raised-cosine swell. Mono, dry, unit
/// gain; the window treatment and the stereo pairing live elsewhere.
///
/// A roll is a "sudden" sound: it reads `sudden` once, at the second it begins, and is born only if
/// a hashed unit is under its base chance (1 at full rate) times `rateScale`; its gain is `gainDB`.
/// So `rateScale == 0` means no roll is ever born and the output is exactly 0.
///
/// Seekable by construction. Time is a grid of 240 s cells, each holding at most one roll whose
/// start lies in the first 120 s of the cell, so neighbouring rolls are 2...6 minutes apart at full
/// rate; a roll (at most 10 s) never leaves its cell, so one stored roll is all the state there is.
/// The rumble is hash noise keyed by absolute frame, so a render started at any second matches a
/// continuous one once the filters (a few tens of milliseconds) have settled.
public struct ThunderSound: SoundSource {
    // MARK: - Values from the plan (placeholders recorded in docs/project-state.md)

    static let gapRange = 120.0...360.0          // seconds between rolls at full rate (via the grid below)
    static let lengthRange = 4.0...10.0          // seconds
    /// The 10-90% rise time of a roll (the plan's "attack 0.8-2 s", read as a rise time).
    static let riseRange = 0.8...2.0
    static let rumbleHz = 600.0                  // nothing above this survives

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let cellSeconds = 240.0               // with offsetSeconds, gives gaps of 120...360 s
    static let offsetSeconds = 120.0             // a roll starts 0...120 s into its cell
    static let baseChance = 1.0
    /// Fraction of a raised-cosine ramp taken by its 10-90% rise, so ramp = rise / this.
    static let riseFraction = (acos(-0.8) - acos(0.8)) / Double.pi
    static let maxRampShare = 0.6                // the swell never takes more of a roll than this
    static let levelRange = 0.6...1.0
    static let gain = 0.4
    static let noiseLowpassHz = 300.0            // two stages, before the pixellation
    static let noiseNorm = 12.0                  // brings the lowpassed noise to about unit size
    static let holdHz = 2756.25                  // sample-and-hold rate (44.1 kHz / 16)
    static let bits = 6
    static let outputLowpassHz = 450.0           // two stages, after the pixellation: the 600 Hz ceiling
    // NightRandom streams (cell streams 91-95; 90 is the noise).
    static let noiseStream: UInt64 = 90
    static let offsetStream: UInt64 = 91
    static let birthStream: UInt64 = 92
    static let lengthStream: UInt64 = 93
    static let riseStream: UInt64 = 94
    static let levelStream: UInt64 = 95

    // MARK: - State

    struct Roll: Equatable {
        var cell = Int.min
        var start = -1             // absolute frame, or -1 for no roll in this cell
        var length = 0
        var ramp = 0               // frames of the raised-cosine swell
        var amp = 0.0              // level times gain
    }

    private let seed: UInt64
    private let sr: Double
    private let sudden: Curve<Sudden>
    private let cellFrames: Int
    /// Test hook: renders only the roll envelopes (no noise, no pixellation).
    var envelopeOnly = false
    private var frame: Int
    private var current = Roll()
    private var held = 0.0
    private var holdIndex = Int.min
    private var rumble: [Biquad]
    private var output: [Biquad]

    public init(seed: UInt64, sampleRate: Double, startSecond: Double, sudden: Curve<Sudden>) {
        self.seed = seed
        sr = sampleRate
        self.sudden = sudden
        cellFrames = Int((ThunderSound.cellSeconds * sampleRate).rounded())
        frame = max(0, Int((startSecond * sampleRate).rounded()))
        rumble = [Biquad.lowpass(cutoff: ThunderSound.noiseLowpassHz, sampleRate: sampleRate),
                  Biquad.lowpass(cutoff: ThunderSound.noiseLowpassHz, sampleRate: sampleRate)]
        output = [Biquad.lowpass(cutoff: ThunderSound.outputLowpassHz, sampleRate: sampleRate),
                  Biquad.lowpass(cutoff: ThunderSound.outputLowpassHz, sampleRate: sampleRate)]
        current = roll(cell: frame / cellFrames) ?? Roll(cell: frame / cellFrames)
    }

    /// The roll of `cell`, or nil when none is born there (a pure function of seed, cell and the
    /// `sudden` curve at the roll's own start second).
    func roll(cell: Int) -> Roll? {
        let c = UInt64(cell)
        let startSecond = Double(cell) * ThunderSound.cellSeconds
            + ThunderSound.offsetSeconds * NightRandom.unit(seed, ThunderSound.offsetStream, c)
        let s = sudden(startSecond)
        guard NightRandom.unit(seed, ThunderSound.birthStream, c) < ThunderSound.baseChance * s.rateScale else { return nil }
        let lr = ThunderSound.lengthRange
        let length = lr.lowerBound + (lr.upperBound - lr.lowerBound) * NightRandom.unit(seed, ThunderSound.lengthStream, c)
        let rr = ThunderSound.riseRange
        let rise = rr.lowerBound + (rr.upperBound - rr.lowerBound) * NightRandom.unit(seed, ThunderSound.riseStream, c)
        let ramp = min(rise / ThunderSound.riseFraction, ThunderSound.maxRampShare * length)
        let lv = ThunderSound.levelRange
        return Roll(
            cell: cell,
            start: Int((startSecond * sr).rounded()),
            length: Int((length * sr).rounded()),
            ramp: Int((ramp * sr).rounded()),
            amp: ThunderSound.gain * pow(10, s.gainDB / 20)
                * (lv.lowerBound + (lv.upperBound - lv.lowerBound) * NightRandom.unit(seed, ThunderSound.levelStream, c)))
    }

    static func quantise(_ x: Double) -> Double {
        let steps = Double((1 << (bits - 1)) - 1)
        return (max(-1, min(1, x)) * steps).rounded() / steps
    }

    public mutating func render(into out: inout [Float], count: Int) {
        for i in 0..<count {
            let f = frame
            if f / cellFrames != current.cell {
                current = roll(cell: f / cellFrames) ?? Roll(cell: f / cellFrames)
            }
            var n = Float(NightRandom.signed(seed, ThunderSound.noiseStream, UInt64(f)))
            for k in 0..<2 { n = rumble[k].process(n) }
            let h = Int(Double(f) * ThunderSound.holdHz / sr)
            if h != holdIndex { holdIndex = h; held = ThunderSound.quantise(tanh(Double(n) * ThunderSound.noiseNorm)) }
            let age = f - current.start
            var env = 0.0
            if current.start >= 0, age >= 0, age < current.length {
                if age < current.ramp {
                    env = 0.5 * (1 - cos(Double.pi * Double(age) / Double(current.ramp)))
                } else {
                    let tail = Double(current.length - current.ramp)
                    env = 0.5 * (1 + cos(Double.pi * Double(age - current.ramp) / tail))
                }
            }
            env *= current.amp
            if envelopeOnly {
                out[i] = Float(env)
            } else {
                var y = Float(held * env)
                for k in 0..<2 { y = output[k].process(y) }
                out[i] = y
            }
            frame += 1
        }
    }
}
