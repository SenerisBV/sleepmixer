import Foundation

public struct ScheduledSegment: Equatable, Sendable {
    public let index: Int
    public let start: Double
    public let end: Double
}

/// A station's endless broadcast. It depends only on time and drift, never on whether anyone is listening.
///
/// The gap after a segment is not fixed in advance: the next segment starts at the first moment `t >= end`
/// with `(t - end) >= Drift.segmentGap(level(t))` (`endWait` after the last segment, then play wraps to
/// index 0). The level is evaluated as time advances, on a 1 s grid anchored at the segment's end, so a
/// reset that lowers the level mid-gap shortens the gap at once. With a constant level the gap is exact.
/// Only the current segment is held, so memory stays constant however long the night runs.
public struct StationProgram: Sendable {
    private let lengths: [Double]
    private let level: @Sendable (Double) -> DriftLevel
    private var current: ScheduledSegment?
    /// Whole seconds after `current.end` whose grid point has already been checked.
    private var scanned = 0

    public init(segmentSeconds: [Double], seed: UInt64, level: @escaping @Sendable (Double) -> DriftLevel) {
        lengths = segmentSeconds.map { $0.isFinite ? max(0, $0) : 0 }
        self.level = level
        guard !lengths.isEmpty else { return }
        let n = lengths.count
        let k = min(n - 1, Int(NightRandom.unit(seed, 50, 0) * Double(n)))
        let start = -NightRandom.unit(seed, 51, 0) * lengths[k]
        current = ScheduledSegment(index: k, start: start, end: start + lengths[k])
    }

    private func gap(after s: ScheduledSegment, _ l: DriftLevel) -> Double {
        s.index == lengths.count - 1 ? Drift.endWait(l) : Drift.segmentGap(l)
    }

    private func nextIndex(after s: ScheduledSegment) -> Int { (s.index + 1) % lengths.count }

    /// Walk the grid forward until `second`, starting the next segment as soon as the level allows.
    private mutating func advance(to second: Double) {
        guard var cur = current else { return }
        while second >= cur.end {
            let t = cur.end + Double(scanned + 1)
            if t > second { break }
            let g = gap(after: cur, level(t))
            if Double(scanned + 1) >= g {
                // Crossed inside (t-1, t]: the exact start for a locally constant level, never before t-1.
                let start = max(cur.end + Double(scanned), cur.end + g)
                let i = nextIndex(after: cur)
                cur = ScheduledSegment(index: i, start: start, end: start + lengths[i])
                scanned = 0
            } else {
                scanned += 1
            }
        }
        current = cur
    }

    /// The segment playing at `second`, or nil in a gap (or for an empty station).
    /// `second` must not decrease between calls; if it does, the answer is based on the current
    /// state (the schedule never rewinds) and nothing traps. Non-finite input returns nil.
    public mutating func segment(at second: Double) -> ScheduledSegment? {
        guard second.isFinite else { return nil }
        advance(to: second)
        guard let cur = current, cur.start <= second, second < cur.end else { return nil }
        return cur
    }

    /// An ESTIMATE of the next segment that starts after `second`, for preloading only. If the current
    /// segment is still ahead it is returned as is; otherwise the start is implied by the level at
    /// `second` and may move if the level changes (e.g. a reset). Same no-rewind rule as `segment(at:)`.
    public mutating func upcoming(after second: Double) -> ScheduledSegment? {
        guard second.isFinite else { return nil }
        advance(to: second)
        guard let cur = current else { return nil }
        if cur.start > second { return cur }
        let i = nextIndex(after: cur)
        let start = max(cur.end + gap(after: cur, level(max(second, cur.end))), second.nextUp)
        return ScheduledSegment(index: i, start: start, end: start + lengths[i])
    }
}
