import Testing
import Foundation
@testable import NightPlan

@Test func nightIsDeterministicAndVaries() {
    #expect(Weather.night(seed: 7) == Weather.night(seed: 7))
    let seen = Set((0..<400).map { Weather.night(seed: UInt64($0)) })
    #expect(seen == Set(WindowNight.allCases))
}

@Test func nightWeightsRoughlyHold() {   // rain .3, rainThunder .25, cricketsStream .25, fire .2
    let n = 4000
    let c = Dictionary(grouping: (0..<n).map { Weather.night(seed: UInt64($0)) }, by: { $0 }).mapValues { Double($0.count) / Double(n) }
    #expect(abs(c[.rain]! - 0.30) < 0.04)
    #expect(abs(c[.fire]! - 0.20) < 0.04)
}

@Test func suddenIsFullEarlyAndSilentDeep() {
    #expect(Weather.sudden(DriftLevel(free: 0, ratchet: 0)) == Sudden(rateScale: 1, gainDB: 0))
    let deep = Weather.sudden(DriftLevel(free: 0.9, ratchet: 0.6))
    #expect(deep.rateScale == 0)
    #expect(Weather.sudden(DriftLevel(free: 1, ratchet: 0.85)).rateScale == 0)
    let mid = Weather.sudden(DriftLevel(free: 0.3, ratchet: 0.3))
    #expect(mid.rateScale > 0 && mid.rateScale < 1 && mid.gainDB < 0 && mid.gainDB > -18)
}

@Test func suddenFollowsTimeSinceOnOnly() {
    #expect(Weather.sudden(secondsSinceOn: 0, seed: 1).rateScale == 1)
    #expect(Weather.sudden(secondsSinceOn: 6 * 3600, seed: 1).rateScale == 0)
    // monotonic: it never comes back
    var last = 1.0
    for t in stride(from: 0.0, through: 6 * 3600, by: 300) {
        let r = Weather.sudden(secondsSinceOn: t, seed: 3).rateScale
        #expect(r <= last)
        last = r
    }
}
