import Testing
import Foundation
@testable import NightPlan

private let lens: [Double] = [120, 200, 90, 300]
private let calm: @Sendable (Double) -> DriftLevel = { _ in DriftLevel(free: 0, ratchet: 0) }
private let deep: @Sendable (Double) -> DriftLevel = { _ in DriftLevel(free: 1, ratchet: 1) }
private let eightHours = 8.0 * 3600

/// Walk the schedule over `horizon` seconds, collecting each distinct segment once.
private func walk(_ p: inout StationProgram, horizon: Double = eightHours) -> [ScheduledSegment] {
    var out: [ScheduledSegment] = []
    var t = 0.0
    while t < horizon {
        if let s = p.segment(at: t), out.last != s { out.append(s) }
        t += 1
    }
    return out
}

@Test func startsMidSegment() {
    for seed in UInt64(0)..<20 {
        var p = StationProgram(segmentSeconds: lens, seed: seed, level: calm)
        let s = p.segment(at: 0)
        #expect(s != nil)
        if let s { #expect(s.start <= 0 && 0 < s.end) }
    }
}

@Test func deterministic() {
    var a = StationProgram(segmentSeconds: lens, seed: 11, level: calm)
    var b = StationProgram(segmentSeconds: lens, seed: 11, level: calm)
    #expect(walk(&a) == walk(&b))
}

@Test func gapsFollowDrift() {
    var p = StationProgram(segmentSeconds: [100, 100, 100], seed: 3, level: calm)
    let w = walk(&p, horizon: 2000)
    #expect(w.count > 3)
    // Between non-wrapping neighbours (index i -> i+1) the gap is 3 s.
    for (x, y) in zip(w, w.dropFirst()) where y.index == x.index + 1 {
        #expect(abs((y.start - x.end) - 3) < 1e-9)
    }
    var q = StationProgram(segmentSeconds: [100, 100, 100], seed: 3, level: deep)
    let v = walk(&q, horizon: 5000)
    for (x, y) in zip(v, v.dropFirst()) where y.index == x.index + 1 {
        #expect(abs((y.start - x.end) - 483) < 1e-9)
    }
}

@Test func wrapsAfterWait() {
    var p = StationProgram(segmentSeconds: [50, 60, 70], seed: 5, level: deep)
    let w = walk(&p, horizon: 6000)
    var sawWrap = false
    for (x, y) in zip(w, w.dropFirst()) where x.index == 2 {
        #expect(y.index == 0)
        #expect(abs((y.start - x.end) - 1230) < 1e-9)
        sawWrap = true
    }
    #expect(sawWrap)
}

@Test func segmentsNeverOverlap() {
    let varying: @Sendable (Double) -> DriftLevel = { t in
        let f = min(1, t / 20000)
        return DriftLevel(free: f, ratchet: f)
    }
    var p = StationProgram(segmentSeconds: lens, seed: 9, level: varying)
    let w = walk(&p)
    #expect(w.count > 5)
    for (x, y) in zip(w, w.dropFirst()) { #expect(y.start >= x.end) }
}

@Test func emptyStationIsSilent() {
    var p = StationProgram(segmentSeconds: [], seed: 1, level: calm)
    for t in stride(from: 0.0, to: 1000, by: 50) {
        #expect(p.segment(at: t) == nil)
        #expect(p.upcoming(after: t) == nil)
    }
}

@Test func upcomingIsNextStart() {
    var p = StationProgram(segmentSeconds: lens, seed: 2, level: calm)
    let now = p.segment(at: 0)!
    let next = p.upcoming(after: 0)!
    #expect(next.start > 0 && next.index == (now.index + 1) % lens.count)
}

@Test func backwardsTimeDoesNotCrash() {
    var p = StationProgram(segmentSeconds: lens, seed: 2, level: calm)
    _ = p.segment(at: 5000)
    _ = p.segment(at: 0)
    _ = p.upcoming(after: -100)
}

@Test func recipesMatchTheDial() {
    #expect(StationRecipe.all.map(\.id) == ["the-lantern-accords", "backward-lesson-one", "the-orchard-light"])
    #expect(StationRecipe.all.map(\.dialPosition) == [0.25, 0.55, 0.85])
}
