import Foundation
import NightPlan

/// A glassy brook beyond the window: a soft filtered-noise bed with sparse resonant bubble chirps
/// (rising pitch, felted attack), lightly pixellated. Mono, dry, unit gain; the window treatment and
/// the stereo pairing live elsewhere.
///
/// Seekable by construction (the rain's way). Bubbles live on a fixed grid of cells keyed by
/// absolute frame; each is a Hann-windowed rising sine chirp whose parameters are a pure function of
/// (seed, cell). The bed is hash noise keyed by absolute frame through two filters, and the
/// pixellation (sample-and-hold, bit reduction, lowpass) is keyed to absolute frames too, so a
/// render started at any second matches a continuous one once the filter states have settled.
public struct StreamSound: SoundSource {
    // MARK: - Values from the plan (placeholders recorded in docs/project-state.md)

    static let bubbleHzRange = 400.0...1500.0    // a chirp rises inside this range
    static let bubbleLengthRange = 0.020...0.060 // seconds; Hann window, attack is half
    static let holdHz = 11025.0
    static let bits = 9

    // MARK: - Invented values (placeholders recorded in docs/project-state.md)

    static let cellSeconds = 0.05
    static let bubbleChance = 0.25               // per cell: about 5 bubbles a second
    static let startHzRange = 400.0...1000.0     // log-uniform start pitch
    static let riseRange = 1.3...1.5             // end pitch / start pitch (capped at 1500 Hz)
    static let bubbleLevelRange = 0.4...1.0
    static let bubbleGain = 0.065
    static let bedGain = 0.16
    static let bedSoftClip = 0.55
    static let bedLowpassHz = 1800.0
    static let bedHighpassHz = 250.0
    static let outputLowpassHz = 5000.0
    // NightRandom streams (bed 0; per-cell 1-6).
    static let bedStream: UInt64 = 0
    static let presenceStream: UInt64 = 1
    static let jitterStream: UInt64 = 2
    static let lengthStream: UInt64 = 3
    static let pitchStream: UInt64 = 4
    static let riseStream: UInt64 = 5
    static let levelStream: UInt64 = 6

    // MARK: - State

    private struct Bubble {
        var cell = -1
        var start = 0              // absolute frame
        var length = 0
        var hz0 = 0.0
        var sweep = 0.0            // Hz per second
        var amp = 0.0
    }

    private static let slotCount = 6     // >= ceil((longest bubble + one cell) / cell) + 1
    private let seed: UInt64
    private let sr: Double
    private let cellFrames: Int
    /// Test hook: 0 renders the bubbles alone (to check their attacks without the bed).
    var bedLevel = 1.0
    private var frame: Int
    private var slots = [Bubble](repeating: Bubble(), count: StreamSound.slotCount)
    private var loadedCell: Int
    private var bedLP: Biquad
    private var bedHP: Biquad
    private var outLP: Biquad
    private var held = 0.0
    private var holdIndex = Int.min

    public init(seed: UInt64, sampleRate: Double, startSecond: Double) {
        self.seed = seed
        sr = sampleRate
        cellFrames = max(1, Int((StreamSound.cellSeconds * sampleRate).rounded()))
        frame = max(0, Int((startSecond * sampleRate).rounded()))
        bedLP = Biquad.lowpass(cutoff: StreamSound.bedLowpassHz, sampleRate: sampleRate)
        bedHP = Biquad.highpass(cutoff: StreamSound.bedHighpassHz, sampleRate: sampleRate)
        outLP = Biquad.lowpass(cutoff: StreamSound.outputLowpassHz, sampleRate: sampleRate)
        loadedCell = frame / cellFrames - StreamSound.slotCount
        loadThrough(frame / cellFrames)
    }

    private mutating func loadThrough(_ cell: Int) {
        while loadedCell < cell {
            loadedCell += 1
            if loadedCell >= 0 { slots[loadedCell % StreamSound.slotCount] = bubble(cell: loadedCell) }
        }
    }

    private func bubble(cell: Int) -> Bubble {
        let c = UInt64(cell)
        guard NightRandom.unit(seed, StreamSound.presenceStream, c) < StreamSound.bubbleChance else {
            return Bubble(cell: cell)
        }
        let lr = StreamSound.bubbleLengthRange
        let seconds = lr.lowerBound + (lr.upperBound - lr.lowerBound) * NightRandom.unit(seed, StreamSound.lengthStream, c)
        let sr0 = StreamSound.startHzRange
        let hz0 = sr0.lowerBound * pow(sr0.upperBound / sr0.lowerBound, NightRandom.unit(seed, StreamSound.pitchStream, c))
        let rr = StreamSound.riseRange
        let hz1 = min(StreamSound.bubbleHzRange.upperBound,
                      hz0 * (rr.lowerBound + (rr.upperBound - rr.lowerBound) * NightRandom.unit(seed, StreamSound.riseStream, c)))
        let lv = StreamSound.bubbleLevelRange
        return Bubble(
            cell: cell,
            start: cell * cellFrames + Int(NightRandom.unit(seed, StreamSound.jitterStream, c) * Double(cellFrames)),
            length: Int((seconds * sr).rounded()),
            hz0: hz0,
            sweep: (hz1 - hz0) / seconds,
            amp: StreamSound.bubbleGain * (lv.lowerBound + (lv.upperBound - lv.lowerBound)
                                            * NightRandom.unit(seed, StreamSound.levelStream, c)))
    }

    static func quantise(_ x: Double) -> Double {
        let steps = Double((1 << (bits - 1)) - 1)
        return (max(-1, min(1, x)) * steps).rounded() / steps
    }

    public mutating func render(into out: inout [Float], count: Int) {
        for i in 0..<count {
            let f = frame
            loadThrough(f / cellFrames)
            var x = 0.0
            for k in 0..<StreamSound.slotCount {
                let b = slots[k]
                let age = f - b.start
                guard b.length > 0, age >= 0, age < b.length else { continue }
                let t = Double(age) / sr
                let w = 0.5 * (1 - cos(2 * Double.pi * Double(age) / Double(b.length)))
                x += b.amp * w * sin(2 * Double.pi * (b.hz0 * t + 0.5 * b.sweep * t * t))
            }
            let n = Float(NightRandom.signed(seed, StreamSound.bedStream, UInt64(f)))
            let y = Double(bedHP.process(bedLP.process(n)))
            x += bedLevel * StreamSound.bedGain * StreamSound.bedSoftClip * tanh(y / StreamSound.bedSoftClip)
            let h = Int(Double(f) * StreamSound.holdHz / sr)
            if h != holdIndex { holdIndex = h; held = StreamSound.quantise(x) }
            out[i] = outLP.process(Float(held))
            frame += 1
        }
    }
}
