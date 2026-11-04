import Foundation
import NightDSP
import NightPlan
import Synchronization

/// Fills the engine's rings (three stations, then the static) ahead of the audio callback.
/// Producer side only: one thread at a time calls `fillRound`. Tests inject stubs here.
protocol RingFiller: AnyObject, Sendable {
    /// One round: at most one block into each ring that holds less than `target` frames.
    /// Returns whether anything was written (false: every ring is full, or the filler has stopped).
    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool
}

/// The real filler: the three `StationChain`s and the `StaticChain` of one switch-on.
///
/// The chains are not Sendable and must live on one thread, so they are built lazily by the first
/// `fillRound`, on the producer thread, and never leave it. Rings are filled round-robin, one
/// 2048-frame block each per round, so all four rise together from empty at switch-on.
final class Renderer: RingFiller, @unchecked Sendable {
    private let bundles: [String: StationBundle]
    private let seed: UInt64
    private let clock: DriftClock
    private let sampleRate: Double
    private let blockFrames: Int
    private var sources: [any SoundSource] = []
    private var block: [Float]

    init(bundles: [String: StationBundle], seed: UInt64, clock: DriftClock, sampleRate: Double, blockFrames: Int) {
        self.bundles = bundles
        self.seed = seed
        self.clock = clock
        self.sampleRate = sampleRate
        self.blockFrames = blockFrames
        block = [Float](repeating: 0, count: blockFrames)
    }

    private func build() {
        var s: [any SoundSource] = StationRecipe.all.map {
            StationChain(recipe: $0, bundle: bundles[$0.id], seed: seed, clock: clock, sampleRate: sampleRate)
        }
        s.append(StaticChain(seed: seed, clock: clock, sampleRate: sampleRate))
        sources = s
    }

    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        if sources.isEmpty { build() }
        var any = false
        for i in rings.indices where i < sources.count && rings[i].available < target {
            sources[i].render(into: &block, count: blockFrames)
            _ = block.withUnsafeBufferPointer { rings[i].write($0) }
            any = true
        }
        return any
    }
}

/// The render thread: one `Thread` at `.userInteractive` QoS that keeps the rings topped up to
/// `target`, and sleeps `idleSleepSeconds` whenever a round writes nothing. When idle it asks
/// `onIdle` whether to finish (the engine's switch-off teardown runs there, on this thread).
/// `stop()` asks it to finish and waits until it has.
final class RenderThread: @unchecked Sendable {
    static let idleSleepSeconds = 0.005

    private let rings: [SPSCRing]
    private let target: Int
    private let filler: any RingFiller
    private let onIdle: @Sendable () -> Bool
    private let stopFlag = Atomic<Bool>(false)
    private let finished = DispatchSemaphore(value: 0)
    private let started = Atomic<Bool>(false)
    private let joined = Atomic<Bool>(false)
    /// The render thread's pthread, so `stop()` can tell when it is called from the thread itself.
    private let threadID = Atomic<UInt>(0)
    private let ended = Atomic<Bool>(false)

    /// Whether the thread's loop has returned.
    var hasEnded: Bool { ended.load(ordering: .acquiring) }

    init(rings: [SPSCRing], target: Int, filler: any RingFiller, onIdle: @escaping @Sendable () -> Bool = { false }) {
        self.rings = rings
        self.target = target
        self.filler = filler
        self.onIdle = onIdle
    }

    func start() {
        guard !started.exchange(true, ordering: .sequentiallyConsistent) else { return }
        let t = Thread { [self] in run() }
        t.qualityOfService = .userInteractive
        t.name = "NightRadio.render"
        t.start()
    }

    private func run() {
        threadID.store(UInt(bitPattern: pthread_self()), ordering: .releasing)
        defer {
            ended.store(true, ordering: .releasing)
            finished.signal()
        }
        while !stopFlag.load(ordering: .acquiring) {
            if filler.fillRound(rings, target: target) { continue }
            if onIdle() { return }
            Thread.sleep(forTimeInterval: Self.idleSleepSeconds)
        }
    }

    /// Asks the thread to finish and waits for it. Called from the thread itself (the engine can be
    /// freed there, when `onIdle` held the last reference), it only asks: waiting would deadlock.
    func stop() {
        stopFlag.store(true, ordering: .releasing)
        if threadID.load(ordering: .acquiring) == UInt(bitPattern: pthread_self()) { return }
        guard started.load(ordering: .acquiring), !joined.exchange(true, ordering: .sequentiallyConsistent) else { return }
        finished.wait()
    }
}
