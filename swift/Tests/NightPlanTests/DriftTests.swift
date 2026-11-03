import Testing
import Foundation
@testable import NightPlan

private let seed: UInt64 = 7

@Test func trendHoldsZeroForHalfAnHour() {
    #expect(Drift.level(clock: 1799, seed: seed).ratchet == 0)
}

@Test func trendReaches085AtSixHours() {
    #expect(abs(Drift.level(clock: 21600, seed: seed).ratchet - 0.85) < 1e-9)
    #expect(abs(Drift.level(clock: 30000, seed: seed).ratchet - 0.85) < 1e-9)
}

@Test func ratchetNeverFalls() {
    var prev = 0.0
    for s in stride(from: 0.0, through: 30000, by: 10) {
        let r = Drift.level(clock: s, seed: seed).ratchet
        #expect(r >= prev)
        prev = r
    }
}

@Test func freeStaysInRange() {
    for s in stride(from: 0.0, through: 30000, by: 10) {
        let f = Drift.level(clock: s, seed: seed).free
        #expect(f >= 0 && f <= 1)
    }
}

@Test func channelOnlyNarrows() {
    var prev = Double.infinity
    for s in stride(from: 0.0, through: 30000, by: 10) {
        let h = Drift.channel(Drift.level(clock: s, seed: seed)).highCornerHz
        #expect(h <= prev)
        prev = h
    }
}

@Test func gapGrowsWithDepth() {
    #expect(abs(Drift.segmentGap(DriftLevel(free: 0, ratchet: 0)) - 3) < 1e-9)
    #expect(abs(Drift.segmentGap(DriftLevel(free: 1, ratchet: 0)) - 483) < 1e-9)
}

@Test func resetFadesNotJumps() {
    let clock = DriftClock(seed: seed)
    clock.touch(at: 0)
    let before = clock.level(at: 20000)
    #expect(before.ratchet > 0.5)
    clock.touch(at: 20000)
    #expect(clock.level(at: 20000) == before)
    let mid = clock.level(at: 20002)
    #expect(mid.ratchet < before.ratchet && mid.ratchet > 0)
    #expect(abs(mid.ratchet - before.ratchet / 2) < 1e-9) // raised cosine midpoint, target 0
    let after = clock.level(at: 20004.1)
    #expect(after == Drift.level(clock: 0, seed: seed))
    #expect(after.ratchet == 0)
}

@Test func browsingNeverDeepens() {
    let clock = DriftClock(seed: seed)
    for s in stride(from: 0.0, through: 600, by: 10) { clock.touch(at: s) }
    for s in stride(from: 0.0, through: 600, by: 1) { #expect(clock.level(at: s).ratchet == 0) }
}

@Test func driftStartsAfterSettling() {
    let clock = DriftClock(seed: seed)
    clock.touch(at: 0)
    clock.touch(at: 100)
    #expect(clock.level(at: 100 + 60 + 1800) == Drift.level(clock: 1800, seed: seed))
    #expect(clock.level(at: 100 + 60 + 5000).ratchet > 0)
}

@Test func oldTouchIgnoredAndBeforeFirstIsZero() {
    let clock = DriftClock(seed: seed)
    #expect(clock.level(at: 5) == .zero)
    clock.touch(at: 10)
    clock.touch(at: 5)
    #expect(clock.level(at: 5) == .zero)
    #expect(clock.level(at: 10 + 60 + 20000).ratchet > 0.5)
}
