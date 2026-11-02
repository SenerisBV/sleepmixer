import Foundation
import NightPlan

/// Breaks the sound into pieces: time is cut into 3 s cells and only some are present.
///
/// Cell `i` plays when `unit(seed, 21, i) >= 0.7 * fragmentation(at the cell's start)`, so full
/// fragmentation leaves about 30% of the cells. A boundary between a present and an absent cell
/// crossfades over `fadeSeconds` with a raised cosine, centred on the boundary. The gain is a pure
/// function of the absolute frame, so seeking is exact.
public struct Fragmenter: Processor {
    public static let cellSeconds = 3.0
    public static let fadeSeconds = 0.4

    // Invented (placeholders recorded in Task 8)
    static let stream: UInt64 = 21
    static let maxAbsentFraction = 0.7   // brief value: fragmentation 1 drops 70% of cells

    private let sampleRate: Double
    private let seed: UInt64
    private let warp: Curve<WarpDepth>
    private var frame: Int

    public init(sampleRate: Double, seed: UInt64, warp: Curve<WarpDepth>, startSecond: Double) {
        self.sampleRate = sampleRate
        self.seed = seed
        self.warp = warp
        self.frame = Int((startSecond * sampleRate).rounded())
    }

    func present(cell: Int) -> Double {
        let c = max(cell, 0)
        let depth = warp(Double(c) * Self.cellSeconds).fragmentation
        return NightRandom.unit(seed, Self.stream, UInt64(c)) >= Self.maxAbsentFraction * depth ? 1 : 0
    }

    /// 1 when the cell is present, 0 when absent, raised-cosine crossfaded at the boundaries.
    public func gain(atFrame f: Int) -> Double {
        let t = Double(f) / sampleRate
        let cell = Int((t / Self.cellSeconds).rounded(.down))
        let start = Double(cell) * Self.cellSeconds
        let half = Self.fadeSeconds / 2
        let here = present(cell: cell)
        if t - start < half {
            let x = (t - start) / Self.fadeSeconds + 0.5
            let before = present(cell: cell - 1)
            return before + (here - before) * Envelope.raisedCosine(x)
        }
        let end = start + Self.cellSeconds
        if end - t < half {
            let x = (t - end) / Self.fadeSeconds + 0.5
            let after = present(cell: cell + 1)
            return here + (after - here) * Envelope.raisedCosine(x)
        }
        return here
    }

    public mutating func process(_ buffer: inout [Float], count: Int) {
        for i in 0..<count {
            buffer[i] *= Float(gain(atFrame: frame + i))
        }
        frame += count
    }
}
