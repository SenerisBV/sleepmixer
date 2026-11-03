import Foundation

public struct ScheduledSegment: Equatable, Sendable {
    public let index: Int
    public let start: Double
    public let end: Double
}

/// A station's endless broadcast. It depends only on time and drift, never on whether anyone is listening.
/// The schedule extends lazily and holds only two segments (the latest started one and the one after),
/// so memory stays constant however long the night runs.
public struct StationProgram: Sendable {
    private let lengths: [Double]
    private let level: @Sendable (Double) -> DriftLevel
    private var current: ScheduledSegment?
    private var following: ScheduledSegment?

    public init(segmentSeconds: [Double], seed: UInt64, level: @escaping @Sendable (Double) -> DriftLevel) {
        lengths = segmentSeconds.map { $0.isFinite ? max(0, $0) : 0 }
        self.level = level
        guard !lengths.isEmpty else { return }
        let n = lengths.count
        let k = min(n - 1, Int(NightRandom.unit(seed, 50, 0) * Double(n)))
        let start = -NightRandom.unit(seed, 51, 0) * lengths[k]
        let first = ScheduledSegment(index: k, start: start, end: start + lengths[k])
        current = first
        following = Self.next(after: first, lengths: lengths, level: level)
    }

    /// The segment after `s`: the gap is sized by the level at `s.end`
    /// (`endWait` after the last segment, then play wraps to index 0).
    private static func next(after s: ScheduledSegment, lengths: [Double],
                             level: @Sendable (Double) -> DriftLevel) -> ScheduledSegment {
        let l = level(s.end)
        let last = s.index == lengths.count - 1
        let gap = last ? Drift.endWait(l) : Drift.segmentGap(l)
        let i = last ? 0 : s.index + 1
        let start = s.end + gap
        return ScheduledSegment(index: i, start: start, end: start + lengths[i])
    }

    /// Slide the window forward while the following segment has already started by `second`.
    private mutating func advance(to second: Double) {
        guard var cur = current, var nxt = following else { return }
        while nxt.start <= second {
            cur = nxt
            nxt = Self.next(after: cur, lengths: lengths, level: level)
        }
        current = cur
        following = nxt
    }

    /// The segment playing at `second`, or nil in a gap (or for an empty station).
    /// `second` must not decrease between calls; if it does, the answer is based on the current
    /// state (the schedule never rewinds) and nothing traps.
    public mutating func segment(at second: Double) -> ScheduledSegment? {
        guard !second.isNaN else { return nil }
        advance(to: second)
        guard let cur = current, cur.start <= second, second < cur.end else { return nil }
        return cur
    }

    /// The next segment that starts after `second` (for preloading). Same no-rewind rule as `segment(at:)`.
    public mutating func upcoming(after second: Double) -> ScheduledSegment? {
        guard !second.isNaN else { return nil }
        advance(to: second)
        if let cur = current, cur.start > second { return cur }
        return following
    }
}
