import Foundation
import NightPlan

/// Soft pixellated crickets heard through a window: very quiet, sparse trains of three short
/// chirps at about 4.5 kHz with long pauses between spells. Mono, dry; the window treatment and the
/// stereo pairing live elsewhere. Its own level already sits about 12 dB under `RainSound`, so the
/// two can share a window gain.
///
/// Seekable by construction (the rain's and the chimes' way). Time is a grid of one-second cells,
/// each holding at most one train whose start is a pure function of (seed, cell); because the
/// offset lies in 0.25...0.75 s the gap between neighbouring trains is 0.5...1.5 s, and a train
/// (under 0.25 s long) never leaves its own cell, so one preallocated train is all the state there
/// is. Pauses live on a coarser grid of cycles: each cycle holds one silent stretch, and any train
/// that would touch it is dropped, so a pause is truly silent (no fade is needed, every pulse has
/// its own Hann envelope). The pixellation (sample-and-hold, bit reduction, lowpass) is keyed to
/// absolute frames.
public struct CricketsSound: SoundSource {
    // MARK: - Values from the plan (placeholders recorded in docs/project-state.md)

    static let carrierHz = 4500.0
    static let pulsesPerTrain = 3
    static let trainGapRange = 0.5...1.5         // seconds between trains (via the cell grid below)
    static let pauseRange = 5.0...20.0           // seconds

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let cellSeconds = 1.0
    static let trainOffsetRange = 0.25...0.75    // offset inside a cell; gives gaps of 0.5...1.5 s
    static let pulseLength = 0.040               // seconds, Hann envelope (attack 20 ms)
    static let pulseSpacing = 0.080              // seconds, start to start
    static let carrierJitter = 0.03              // +/- fraction per train
    static let levelRange = 0.6...1.0
    static let gain = 0.18
    static let cycleSeconds = 45.0               // one pause per cycle, >= 10 s of crickets between
    static let pauseGuard = 5.0                  // a pause starts at least this far into its cycle
    static let holdHz = 11025.0
    static let bits = 8
    static let outputLowpassHz = 5200.0
    // NightRandom streams (all per cell or per cycle).
    static let offsetStream: UInt64 = 80
    static let hzStream: UInt64 = 81
    static let levelStream: UInt64 = 82
    static let pauseStartStream: UInt64 = 83
    static let pauseLengthStream: UInt64 = 84

    // MARK: - State

    private struct Train {
        var cell = Int.min
        var start = 0              // absolute frame of the first pulse, or -1 for none
        var omega = 0.0
        var amp = 0.0
    }

    private let seed: UInt64
    private let sr: Double
    private let cellFrames: Int
    private let pulseFrames: Int, spacingFrames: Int
    /// Test hook: renders only the pulse envelopes (constant carrier, no pixellation).
    var envelopeOnly = false
    private var frame: Int
    private var train = Train()
    private var held = 0.0
    private var holdIndex = Int.min
    private var lowpass: Biquad

    public init(seed: UInt64, sampleRate: Double, startSecond: Double) {
        self.seed = seed
        sr = sampleRate
        cellFrames = Int((CricketsSound.cellSeconds * sampleRate).rounded())
        pulseFrames = Int((CricketsSound.pulseLength * sampleRate).rounded())
        spacingFrames = Int((CricketsSound.pulseSpacing * sampleRate).rounded())
        frame = max(0, Int((startSecond * sampleRate).rounded()))
        lowpass = Biquad.lowpass(cutoff: CricketsSound.outputLowpassHz, sampleRate: sampleRate)
        train = makeTrain(cell: frame / cellFrames)
    }

    /// The pause of the cycle containing `cycle`, as seconds (start, end).
    private func pause(cycle: Int) -> (Double, Double) {
        let c = UInt64(cycle)
        let pr = CricketsSound.pauseRange
        let length = pr.lowerBound + (pr.upperBound - pr.lowerBound) * NightRandom.unit(seed, CricketsSound.pauseLengthStream, c)
        let lo = CricketsSound.pauseGuard
        let hi = CricketsSound.cycleSeconds - CricketsSound.pauseGuard - length
        let start = Double(cycle) * CricketsSound.cycleSeconds + lo + (hi - lo) * NightRandom.unit(seed, CricketsSound.pauseStartStream, c)
        return (start, start + length)
    }

    private func makeTrain(cell: Int) -> Train {
        let c = UInt64(cell)
        let o = CricketsSound.trainOffsetRange
        let startSecond = (Double(cell) + o.lowerBound + (o.upperBound - o.lowerBound)
                           * NightRandom.unit(seed, CricketsSound.offsetStream, c)) * CricketsSound.cellSeconds
        let endSecond = startSecond + Double(CricketsSound.pulsesPerTrain - 1) * CricketsSound.pulseSpacing
            + CricketsSound.pulseLength
        let (pauseStart, pauseEnd) = pause(cycle: Int(startSecond / CricketsSound.cycleSeconds))
        guard endSecond < pauseStart || startSecond > pauseEnd else { return Train(cell: cell, start: -1) }
        let hz = CricketsSound.carrierHz * (1 + CricketsSound.carrierJitter
            * (2 * NightRandom.unit(seed, CricketsSound.hzStream, c) - 1))
        let lv = CricketsSound.levelRange
        return Train(
            cell: cell,
            start: Int((startSecond * sr).rounded()),
            omega: 2 * Double.pi * hz / sr,
            amp: CricketsSound.gain * (lv.lowerBound + (lv.upperBound - lv.lowerBound)
                                        * NightRandom.unit(seed, CricketsSound.levelStream, c)))
    }

    static func quantise(_ x: Double) -> Double {
        let steps = Double((1 << (bits - 1)) - 1)
        return (max(-1, min(1, x)) * steps).rounded() / steps
    }

    public mutating func render(into out: inout [Float], count: Int) {
        for i in 0..<count {
            let f = frame
            if f / cellFrames != train.cell { train = makeTrain(cell: f / cellFrames) }
            var x = 0.0
            if train.start >= 0 {
                for k in 0..<CricketsSound.pulsesPerTrain {
                    let age = f - train.start - k * spacingFrames
                    guard age >= 0, age < pulseFrames else { continue }
                    let w = 0.5 * (1 - cos(2 * Double.pi * Double(age) / Double(pulseFrames)))
                    x += train.amp * w * (envelopeOnly ? 1 : sin(train.omega * Double(age)))
                }
            }
            if envelopeOnly {
                out[i] = Float(x)
            } else {
                let h = Int(Double(f) * CricketsSound.holdHz / sr)
                if h != holdIndex { holdIndex = h; held = CricketsSound.quantise(x) }
                out[i] = lowpass.process(Float(held))
            }
            frame += 1
        }
    }
}
