import Testing
@testable import NightPlan

@Test func hashIsDeterministicAndSpread() {
    #expect(NightRandom.hash(7, 1, 42) == NightRandom.hash(7, 1, 42))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(7, 1, 43))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(7, 2, 42))
    #expect(NightRandom.hash(7, 1, 42) != NightRandom.hash(8, 1, 42))
    let u = (0..<10_000).map { NightRandom.unit(1, 0, UInt64($0)) }
    #expect(u.allSatisfy { $0 >= 0 && $0 < 1 })
    #expect(abs(u.reduce(0, +) / 10_000 - 0.5) < 0.02)
}
@Test func hashGoldenValue() {   // pins the algorithm so Swift on every device agrees
    #expect(NightRandom.hash(0, 0, 0) == 0xE220A8397B1DCDAF)   // SplitMix64's canonical first output for seed 0
}
@Test func warpClampsEveryField() {
    let w = WarpDepth(distance: 1.5, slowness: -0.2, fragmentation: .nan, proportion: 0.4)
    #expect(w == WarpDepth(distance: 1, slowness: 0, fragmentation: 0, proportion: 0.4))
}
@Test func channelClampsAndKeepsAnOctave() {
    var c = ChannelSettings.early; c.highCornerHz = 200; c.lowCornerHz = 300
    #expect(c.highCornerHz >= c.lowCornerHz * 2)
}
@Test func constantCurve() { #expect(Curve.constant(3.0)(28_800) == 3.0) }
@Test func octaveRaisesHigh() {
    var c = ChannelSettings.early
    c.highCornerHz = 800; c.lowCornerHz = 500
    #expect(c.highCornerHz == 1000)
    c.lowCornerHz = 1000
    #expect(c.highCornerHz >= 2000)
}
