import Foundation
import NightDSP
import NightPlan

/// The sound of one station: three generated beds and its spoken word, all through one AM channel.
///
///     warmth/chimes/waves × recipe gain × bed gain -> Fragmenter -> Distance (bed warp)
///     + StationVoice (voice gain, voice Distance)
///     -> AMChannel (Drift.channel) -> master guard
///
/// Works in engine seconds since the radio switched on (frame / sampleRate), starting cold at 0.
/// Every warp and channel curve reads the shared `DriftClock` directly (O(log n) under a Mutex, at
/// most once per 512-frame block per processor and per scene event: cheap enough, see the perf test).
/// Runs on the render thread only: the voice loads files. Buffers are preallocated; none per block.
public struct StationChain: SoundSource {
    /// Placeholder (docs/project-state.md, "Plan 9"): the beds sit 8 dB down before the channel.
    public static let bedGainDB = -8.0
    static let initialCapacity = 4096

    // Seed streams `k` of NightRandom.hash(seed, stationIndex, k).
    static let warmthK: UInt64 = 0, chimesK: UInt64 = 1, wavesK: UInt64 = 2
    static let fragmenterK: UInt64 = 3, bedDistanceK: UInt64 = 4, channelK: UInt64 = 5
    static let programK: UInt64 = 6, voiceDistanceK: UInt64 = 7

    /// The station's index in `StationRecipe.all` (an unknown id gets the slot after the last).
    public static func stationIndex(_ recipe: StationRecipe) -> UInt64 {
        UInt64(StationRecipe.all.firstIndex { $0.id == recipe.id } ?? StationRecipe.all.count + 1)
    }

    /// The seed of the station's broadcast schedule (exposed so tests can pick a starting segment).
    public static func programSeed(_ seed: UInt64, recipe: StationRecipe) -> UInt64 {
        NightRandom.hash(seed, stationIndex(recipe), programK)
    }

    private let sampleRate: Double
    private let gains: (warmth: Float, chimes: Float, waves: Float)
    private var warmth: LowWarmthScene
    private var chimes: ChimesScene
    private var waves: WavesScene
    private var fragmenter: Fragmenter
    private var distance: Distance
    private var voice: StationVoice?
    private var channel: AMChannel
    private var scratch: [Float]

    public init(recipe: StationRecipe, bundle: StationBundle?, seed: UInt64, clock: DriftClock,
                sampleRate: Double,
                loader: @escaping @Sendable (URL) -> VoiceClip? = { try? VoiceClip.load(url: $0) }) {
        self.sampleRate = sampleRate
        let station = Self.stationIndex(recipe)
        func s(_ k: UInt64) -> UInt64 { NightRandom.hash(seed, station, k) }
        let bed = pow(10, Self.bedGainDB / 20)
        gains = (Float(recipe.warmth * bed), Float(recipe.chimes * bed), Float(recipe.waves * bed))

        let warp = Curve<WarpDepth> { [clock] in Drift.bedWarp(clock.level(at: $0)) }
        warmth = LowWarmthScene(seed: s(Self.warmthK), sampleRate: sampleRate, warp: warp, startSecond: 0)
        chimes = ChimesScene(seed: s(Self.chimesK), sampleRate: sampleRate, warp: warp, startSecond: 0)
        waves = WavesScene(seed: s(Self.wavesK), sampleRate: sampleRate, warp: warp, startSecond: 0)
        fragmenter = Fragmenter(sampleRate: sampleRate, seed: s(Self.fragmenterK), warp: warp, startSecond: 0)
        distance = Distance(sampleRate: sampleRate, seed: s(Self.bedDistanceK), warp: warp, startSecond: 0)
        voice = bundle.flatMap { b in
            b.segmentSeconds.isEmpty ? nil
                : StationVoice(bundle: b, programSeed: s(Self.programK), distanceSeed: s(Self.voiceDistanceK),
                               clock: clock, sampleRate: sampleRate, loader: loader)
        }
        channel = AMChannel(sampleRate: sampleRate, seed: s(Self.channelK),
                            settings: Curve { [clock] in Drift.channel(clock.level(at: $0)) }, startSecond: 0)
        scratch = [Float](repeating: 0, count: Self.initialCapacity)
    }

    public mutating func render(into out: inout [Float], count: Int) {
        guard count > 0 else { return }
        if scratch.count < count { scratch = [Float](repeating: 0, count: count) }

        warmth.render(into: &out, count: count)
        for i in 0..<count { out[i] *= gains.warmth }
        chimes.render(into: &scratch, count: count)
        for i in 0..<count { out[i] += gains.chimes * scratch[i] }
        waves.render(into: &scratch, count: count)
        for i in 0..<count { out[i] += gains.waves * scratch[i] }
        fragmenter.process(&out, count: count)
        distance.process(&out, count: count)

        if voice != nil {
            voice!.render(into: &scratch, count: count)
            for i in 0..<count { out[i] += scratch[i] }
        }

        channel.process(&out, count: count)
        for i in 0..<count { out[i] = NightFactory.masterGuard(out[i]) }
    }
}
