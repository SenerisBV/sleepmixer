import Foundation
import NightPlan

/// "Different proportions": per event, one element swells by `favouredDB × p` and the others
/// recede by `recededDB × p`. Shared by every scene so the rule is stated once.
enum Proportion {
    static let favouredDB = 6.0
    static let recededDB = -12.0

    /// The favoured element for event `index`, drawn from `stream`.
    private static func favoured(seed: UInt64, stream: UInt64, index: UInt64, count: Int) -> Int {
        min(Int(NightRandom.unit(seed, stream, index) * Double(count)), count - 1)
    }

    /// Per-element gains in dB for event `index`, the favoured element drawn from `stream`.
    /// Not power-preserving: the waves still use it unchanged.
    static func gainsDB(seed: UInt64, stream: UInt64, index: UInt64, count: Int, proportion: Double) -> [Double] {
        let favoured = favoured(seed: seed, stream: stream, index: index, count: count)
        return (0..<count).map { $0 == favoured ? favouredDB * proportion : recededDB * proportion }
    }

    /// Linear gains, applied on top of `baseAmps`, in the `gainsDB` shape (favoured `+6p` dB, the
    /// rest `-12p` dB) rescaled so that `Σ (base_i · g_i)²` equals `Σ base_i²`: proportion
    /// reweights an event without making it louder or quieter.
    static func powerPreservingGains(seed: UInt64, stream: UInt64, index: UInt64, baseAmps: [Double], proportion: Double) -> [Double] {
        let f = favoured(seed: seed, stream: stream, index: index, count: baseAmps.count)
        return powerPreservingGains(favoured: f, baseAmps: baseAmps, proportion: proportion)
    }

    /// The same, for an explicitly chosen favoured element.
    static func powerPreservingGains(favoured: Int, baseAmps: [Double], proportion: Double) -> [Double] {
        let shape = baseAmps.indices.map { pow(10, ($0 == favoured ? favouredDB : recededDB) * proportion / 20) }
        var target = 0.0, shaped = 0.0
        for (b, g) in zip(baseAmps, shape) { target += b * b; shaped += b * g * b * g }
        let scale = shaped > 0 ? (target / shaped).squareRoot() : 1
        return shape.map { $0 * scale }
    }
}
