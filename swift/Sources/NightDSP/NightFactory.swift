import Foundation
import NightPlan

public struct AuditionRequest: Equatable, Sendable {
    public var scene: SceneKind
    public var seconds: Double
    public var startSecond: Double
    public var seed: UInt64
    public var warp: WarpDepth
    public var channel: Bool
    public var channelSettings: ChannelSettings
    public var sampleRate: Double

    public init(scene: SceneKind, seconds: Double = 60, startSecond: Double = 0, seed: UInt64 = 1,
                warp: WarpDepth = .plain, channel: Bool = true,
                channelSettings: ChannelSettings = .early, sampleRate: Double = 44100) {
        self.scene = scene
        self.seconds = seconds
        self.startSecond = startSecond
        self.seed = seed
        self.warp = warp
        self.channel = channel
        self.channelSettings = channelSettings
        self.sampleRate = sampleRate
    }
}

/// The single factory: the app and `nightctl` both build sound only through here.
/// Chain: scene -> Fragmenter -> Distance -> AMChannel (optional) -> master guard.
public enum NightFactory {
    /// Seconds rendered before the requested start and discarded (longest stateful tail: 4.5 s
    /// reverb plus filter settling).
    public static let leadInSeconds = 6.0
    static let blockFrames = 4096
    static let kneeStart: Float = 0.5011872   // -6 dBFS
    static let ceiling: Float = 0.8912509     // -1 dBFS

    /// Unity below -6 dBFS; above, a tanh knee that approaches the -1 dBFS ceiling. Value and
    /// slope (1) are continuous at the knee: y = k + (c - k) * tanh((|x| - k) / (c - k)).
    public static func masterGuard(_ x: Float) -> Float {
        guard x.isFinite else { return 0 }
        let a = abs(x)
        if a <= kneeStart { return x }
        let room = ceiling - kneeStart
        let y = kneeStart + room * tanhf((a - kneeStart) / room)
        return x < 0 ? -y : y
    }

    public static func audition(_ r: AuditionRequest) -> [Float] {
        switch r.scene {
        case .chimes: return build(ChimesScene.self, r)
        case .waves: return build(WavesScene.self, r)
        }
    }

    private static func build<S: Scene>(_ type: S.Type, _ r: AuditionRequest) -> [Float] {
        let sr = r.sampleRate
        let startSecond = r.startSecond.isFinite ? max(0, r.startSecond) : 0
        let start = max(0, startSecond - leadInSeconds)
        let lead = Int(((startSecond - start) * sr).rounded())
        let wanted = max(0, Int((r.seconds * sr).rounded()))
        let warp = Curve<WarpDepth>.constant(r.warp)

        var scene = S(seed: NightRandom.hash(r.seed, 0, 0), sampleRate: sr, warp: warp, startSecond: start)
        var fragmenter = Fragmenter(sampleRate: sr, seed: NightRandom.hash(r.seed, 1, 0), warp: warp, startSecond: start)
        var distance = Distance(sampleRate: sr, seed: NightRandom.hash(r.seed, 2, 0), warp: warp, startSecond: start)
        var channel: AMChannel? = r.channel
            ? AMChannel(sampleRate: sr, seed: NightRandom.hash(r.seed, 3, 0),
                        settings: .constant(r.channelSettings), startSecond: start)
            : nil

        var result = [Float]()
        result.reserveCapacity(wanted)
        var block = [Float](repeating: 0, count: blockFrames)
        var produced = 0
        let total = lead + wanted
        while produced < total {
            let n = min(blockFrames, total - produced)
            scene.render(into: &block, count: n)
            fragmenter.process(&block, count: n)
            distance.process(&block, count: n)
            channel?.process(&block, count: n)
            for i in 0..<n where produced + i >= lead {
                result.append(masterGuard(block[i]))
            }
            produced += n
        }
        return result
    }
}
