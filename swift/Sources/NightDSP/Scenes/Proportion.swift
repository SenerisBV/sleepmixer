import Foundation
import NightPlan

/// "Different proportions": per event, one element swells by `favouredDB × p` and the others
/// recede by `recededDB × p`. Shared by every scene so the rule is stated once.
enum Proportion {
    static let favouredDB = 6.0
    static let recededDB = -12.0

    /// Per-element gains in dB for event `index`, the favoured element drawn from `stream`.
    static func gainsDB(seed: UInt64, stream: UInt64, index: UInt64, count: Int, proportion: Double) -> [Double] {
        let favoured = min(Int(NightRandom.unit(seed, stream, index) * Double(count)), count - 1)
        return (0..<count).map { $0 == favoured ? favouredDB * proportion : recededDB * proportion }
    }
}
