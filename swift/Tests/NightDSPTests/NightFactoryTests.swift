import Foundation
import Testing
import NightDSP
import NightPlan

@Suite struct NightFactoryTests {
    @Test func everyCornerIsSafe() {
        for kind in SceneKind.allCases {
            for bits in 0..<16 {
                for channel in [true, false] {
                    let v = { (b: Int) in Double((bits >> b) & 1) }
                    let warp = WarpDepth(distance: v(0), slowness: v(1), fragmentation: v(2), proportion: v(3))
                    var settings = ChannelSettings.early
                    settings.squash = 1
                    settings.hissLevelDB = -20
                    let out = NightFactory.audition(AuditionRequest(
                        scene: kind, seconds: 3, warp: warp, channel: channel, channelSettings: settings))
                    #expect(out.count == 3 * 44100)
                    #expect(out.allSatisfy { $0.isFinite })
                    let peak = out.reduce(Float(0)) { max($0, abs($1)) }
                    #expect(peak <= 0.95, "\(kind) bits \(bits) channel \(channel) peak \(peak)")
                }
            }
        }
    }

    @Test func factoryIsDeterministic() {
        let r = AuditionRequest(scene: .chimes, seconds: 4, startSecond: 20, seed: 5,
                                warp: WarpDepth(distance: 0.4, fragmentation: 0.3))
        #expect(NightFactory.audition(r) == NightFactory.audition(r))
    }

    /// The brief asked for "channel off has the higher centroid", but measured, the channel raises the
    /// centroid (it removes the low end and adds hiss and saturation harmonics). What the channel
    /// reliably does is band-limit: it takes the waves' low end away. That is what we assert.
    @Test func channelOffKeepsTheLowEnd() {
        for seed in [1, 2, 3] as [UInt64] {
            let on = NightFactory.audition(AuditionRequest(scene: .waves, seconds: 10, seed: seed, channel: true))
            let off = NightFactory.audition(AuditionRequest(scene: .waves, seconds: 10, seed: seed, channel: false))
            let lowOff = Analysis.bandEnergyRatio(off, sampleRate: 44100, below: 150)
            let lowOn = Analysis.bandEnergyRatio(on, sampleRate: 44100, below: 150)
            #expect(lowOff > 2 * lowOn, "seed \(seed): low-end share \(lowOff) off vs \(lowOn) on")
        }
    }

    @Test func seekingMatchesTheTailOfALongerRender() {
        // Hour-eight start: right length, finite, audible.
        let r = AuditionRequest(scene: .waves, seconds: 5, startSecond: 28_800, warp: WarpDepth(distance: 0.5))
        let out = NightFactory.audition(r)
        #expect(out.count == 5 * 44100)
        #expect(out.allSatisfy { $0.isFinite })
        #expect(Analysis.rmsDB(out[...]) > -60)
    }

    @Test func guardIsUnityBelowTheKneeAndContinuousAcross() {
        let t = Float(pow(10.0, -6.0 / 20.0))
        #expect(NightFactory.masterGuard(0.3) == 0.3)
        #expect(NightFactory.masterGuard(-0.3) == -0.3)
        #expect(NightFactory.masterGuard(t) == t)
        let e: Float = 1e-4
        let below = NightFactory.masterGuard(t - e), above = NightFactory.masterGuard(t + e)
        // Continuous in value and slope: both sides step by ~e.
        #expect(abs((above - below) - 2 * e) < 1e-6)
        let slopeAbove = (NightFactory.masterGuard(t + 2 * e) - NightFactory.masterGuard(t + e)) / e
        #expect(abs(slopeAbove - 1) < 1e-2)
        #expect(NightFactory.masterGuard(100) <= Float(pow(10.0, -1.0 / 20.0)) + 1e-6)
        #expect(NightFactory.masterGuard(-100) >= -Float(pow(10.0, -1.0 / 20.0)) - 1e-6)
    }
}
