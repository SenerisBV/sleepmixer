import Foundation
import Synchronization

/// Engine seconds (since the radio clicked on) -> drift. Thread-safe; touches arrive from the UI,
/// `level(at:)` is read from the render thread (never the audio thread). O(log n) per call.
public final class DriftClock: Sendable {
    public static let settleSeconds = 60.0, resetFadeSeconds = 4.0

    private struct Touch { var second: Double; var d0: DriftLevel }
    private let seed: UInt64
    private let touches = Mutex<[Touch]>([])

    public init(seed: UInt64) { self.seed = seed }

    /// A wheel turn; also called once at 0 when switched on. Older-than-last touches are ignored.
    public func touch(at second: Double) {
        guard !second.isNaN else { return }
        touches.withLock { ts in
            if let last = ts.last, second < last.second { return }
            ts.append(Touch(second: second, d0: Self.level(in: ts, at: second, seed: seed)))
        }
    }

    public func level(at second: Double) -> DriftLevel {
        touches.withLock { Self.level(in: $0, at: second, seed: seed) }
    }

    private static func level(in ts: [Touch], at t: Double, seed: UInt64) -> DriftLevel {
        // last touch with second <= t (binary search)
        var lo = 0, hi = ts.count
        while lo < hi {
            let mid = (lo + hi) / 2
            if ts[mid].second <= t { lo = mid + 1 } else { hi = mid }
        }
        guard lo > 0 else { return .zero }
        let touch = ts[lo - 1]
        let since = t - touch.second
        let target = Drift.level(clock: max(0, since - settleSeconds), seed: seed)
        guard since < resetFadeSeconds else { return target }
        let w = 0.5 * (1 - cos(Double.pi * since / resetFadeSeconds))
        return DriftLevel(free: touch.d0.free + (target.free - touch.d0.free) * w,
                          ratchet: touch.d0.ratchet + (target.ratchet - touch.d0.ratchet) * w)
    }
}
