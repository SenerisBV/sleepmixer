import Foundation
import NightDSP
import NightPlan

/// The static between stations: an AM channel over silence (its hiss, crackle and fading are the
/// sound), × `Drift.staticGainDB`, then the master guard. Engine seconds from 0, render thread only.
public struct StaticChain: SoundSource {
    /// Placeholder (docs/project-state.md, "Plan 9").
    public static let settings = ChannelSettings(lowCornerHz: 300, highCornerHz: 3000, hissLevelDB: -30,
                                                 crackleLevelDB: -36, fadeDepth: 0.4, fadeRateHz: 0.08,
                                                 squash: 0.3)
    /// The static's slot in NightRandom.hash(seed, stationIndex, k): after the three stations.
    static let staticIndex = UInt64(StationRecipe.all.count)

    private let clock: DriftClock
    private let sampleRate: Double
    private var channel: AMChannel
    private var frame = 0
    private var gain: Double

    public init(seed: UInt64, clock: DriftClock, sampleRate: Double) {
        self.clock = clock
        self.sampleRate = sampleRate
        channel = AMChannel(sampleRate: sampleRate, seed: NightRandom.hash(seed, Self.staticIndex, 0),
                            settings: .constant(Self.settings), startSecond: 0)
        gain = Self.linear(Drift.staticGainDB(clock.level(at: 0)))
    }

    static func linear(_ db: Double) -> Double { pow(10, db / 20) }

    public mutating func render(into out: inout [Float], count: Int) {
        guard count > 0 else { return }
        for i in 0..<count { out[i] = 0 }
        channel.process(&out, count: count)
        let target = Self.linear(Drift.staticGainDB(clock.level(at: Double(frame + count - 1) / sampleRate)))
        let g0 = gain
        for i in 0..<count {
            let g = g0 + (target - g0) * Double(i + 1) / Double(count)
            out[i] = NightFactory.masterGuard(out[i] * Float(g))
        }
        gain = target
        frame += count
    }
}
