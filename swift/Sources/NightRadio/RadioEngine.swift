import AVFoundation
import Foundation
import NightDSP
import NightPlan
import Synchronization

/// The live radio: the dial's needle in, stereo audio out.
///
/// **Switching on and off.** `setNeedle` leaving the off zone switches on: a new `DriftClock` with a
/// random seed, touched at 0; empty rings; `nowSecond` back to 0; a new `Renderer` (its chains are
/// built on the render thread); the render thread and the `AVAudioEngine` started; a 2 s fade in.
/// Entering the off zone fades out over 1.5 s. When the fade reaches silence, the render thread
/// tears the session down: it stops the engine, empties the rings and finishes. Leaving the off zone
/// again *before* that (a flick of the wheel) reverses the fade on the same session; it is not a
/// fresh start, because a fresh start under a half-faded sound would be a jump.
///
/// **Threads.** The UI calls `setNeedle`, `wheelTouched`, `pause` and `play`; they serialise on a
/// `Mutex` that the audio callback never touches. `setNeedle` computes `Dial.gains` there (it
/// allocates) and publishes the four gains as `Atomic<UInt32>` Float bit patterns. The render thread
/// owns the chains and writes the rings. The audio callback (`Mixer.render`) reads the rings and the
/// atomics only: no locks, no allocation, no I/O.
///
/// **The callback.** Each ring's gain is smoothed per sample by a 30 ms one-pole; the master fade is a
/// raised cosine of a linear phase that moves at 1 / (fade seconds × 44100) per sample toward its
/// target, so a fade reversed midway turns around without a step. The mono mix goes through the master
/// guard and into every channel of a stereo, non-interleaved Float32 format at 44100 Hz.
///
/// **Underruns.** The callback keeps 5 ms in hand: it only plays a ring while the ring holds a block
/// plus 5 ms. When it does not, the last 5 ms of real frames are faded out (raised cosine) and the
/// missing frames are zeros; when the ring has a block plus 5 ms again, it fades back in over 5 ms.
/// It never waits.
///
/// **Manual rendering (tests).** With `manualRendering: true` the engine runs in AVAudioEngine's
/// offline manual rendering mode and there is no render thread: `renderManually` tops the rings up
/// to the render-ahead target synchronously, on the calling thread, before each chunk it renders,
/// and runs the switch-off teardown after each chunk. The calling thread *is* the render thread, so
/// output is deterministic and never underruns unless the filler stops.
public final class RadioEngine: @unchecked Sendable {
    public static let sampleRate = 44100.0
    /// Placeholders (docs/project-state.md, "Plan 9", Task 8).
    public static let onFadeSeconds = 2.0, offFadeSeconds = 1.5, pauseFadeSeconds = 1.5
    /// Placeholder (docs/project-state.md, "Plan 9", Task 9): the fade when the output route is lost.
    public static let routeLossFadeSeconds = 0.05
    static let renderAheadFrames = 66150          // 1.5 s
    static let blockFrames = 2048
    static let ringCapacity = 88200               // 2 s: the target plus a block always fits
    static let manualChunkFrames = 4096

    private struct Session {
        let generation: Int
        let clock: DriftClock
        let filler: any RingFiller
        let thread: RenderThread?
    }

    private struct Control {
        var on = false
        var paused = false
        var generation = 0
        var session: Session?
        /// The render thread (or `renderManually`) is stopping the engine outside the lock.
        var tearingDown = false
    }

    private let mixer: Mixer
    private let engine = AVAudioEngine()
    private let sourceNode: AVAudioSourceNode
    private let manual: Bool
    private let manualSetupError: Error?
    private let makeFiller: @Sendable (UInt64, DriftClock) -> any RingFiller
    private let makeClock: @Sendable (UInt64) -> DriftClock
    private let control = Mutex(Control())

    var rings: [SPSCRing] { mixer.rings }

    public convenience init(bundles: [String: StationBundle], manualRendering: Bool = false) {
        self.init(bundles: bundles, manualRendering: manualRendering, makeFiller: { seed, clock in
            Renderer(bundles: bundles, seed: seed, clock: clock, sampleRate: Self.sampleRate,
                     blockFrames: Self.blockFrames)
        })
    }

    /// The filler seam: tests pass a stub that stops writing, to make the callback underrun.
    /// The clock seam: a new, already touched clock per switch-on (tests start one deep in the night).
    init(bundles: [String: StationBundle], manualRendering: Bool,
         makeFiller: @escaping @Sendable (_ seed: UInt64, _ clock: DriftClock) -> any RingFiller,
         makeClock: @escaping @Sendable (_ seed: UInt64) -> DriftClock = { seed in
             let clock = DriftClock(seed: seed)
             clock.touch(at: 0)
             return clock
         }) {
        manual = manualRendering
        self.makeFiller = makeFiller
        self.makeClock = makeClock
        let mixer = Mixer(rings: (0..<(StationRecipe.all.count + 1)).map { _ in SPSCRing(capacity: Self.ringCapacity) },
                          sampleRate: Self.sampleRate, maxChunk: Self.manualChunkFrames)
        self.mixer = mixer
        let format = AVAudioFormat(standardFormatWithSampleRate: Self.sampleRate, channels: 2)!
        sourceNode = AVAudioSourceNode(format: format) { _, _, frameCount, buffers in
            mixer.render(frameCount: Int(frameCount), into: buffers)
            return noErr
        }
        var setupError: Error?
        if manualRendering {
            do {
                try engine.enableManualRenderingMode(.offline, format: format,
                                                     maximumFrameCount: AVAudioFrameCount(Self.manualChunkFrames))
            } catch { setupError = error }
        }
        manualSetupError = setupError
        engine.attach(sourceNode)
        engine.connect(sourceNode, to: engine.mainMixerNode, format: format)
    }

    deinit {
        let thread = control.withLock { c -> RenderThread? in
            let t = c.session?.thread
            c.session = nil
            return t
        }
        thread?.stop()
        engine.stop()
    }

    // MARK: UI side

    /// From the UI. Leaving the off zone switches on; entering it switches off (both faded).
    public func setNeedle(_ needle: Double) {
        mixer.needleBits.store(needle.bitPattern, ordering: .relaxed)
        let g = Dial.gains(needle: needle, stations: StationRecipe.all)
        control.withLock { c in
            // Off-zone gains (all zero) are not published: the off-fade keeps the last sound.
            if g.isOn { mixer.publish(stations: g.stations, staticGain: g.staticGain) }
            if g.isOn && !c.on {
                switchOn(&c)
            } else if !g.isOn && c.on {
                c.on = false
                c.paused = false
                if c.session != nil {
                    mixer.offRequested.store(true, ordering: .releasing)
                    mixer.setMaster(up: false, seconds: Self.offFadeSeconds)
                }
            }
        }
    }

    /// A turn of the wheel: the drift resets to bedtime clarity. No-op while off.
    ///
    /// The touch lands at the producer's position, not the audible `nowSecond`: the chains have
    /// already rendered up to 1.5 s ahead at the old depth, and a touch behind that would make the
    /// drift step where the rendered audio runs out. So the reset is heard up to 1.5 s after the touch.
    public func wheelTouched() {
        control.withLock { c in
            guard c.on, !c.tearingDown, let s = c.session else { return }
            s.clock.touch(at: producerSecond)
        }
    }

    /// Past every frame the producer has rendered or may be rendering: the furthest ring's written
    /// frames plus one block in flight.
    var producerSecond: Double {
        let written = mixer.rings.reduce(0) { max($0, $1.producedFrames) }
        return Double(written + Self.blockFrames) / Self.sampleRate
    }

    /// Fades out over 1.5 s; the engine and the clock keep running.
    public func pause() {
        control.withLock { c in
            guard c.on, !c.tearingDown, c.session != nil, !c.paused else { return }
            c.paused = true
            mixer.setMaster(up: false, seconds: Self.pauseFadeSeconds)
        }
    }

    /// Fades back in over 1.5 s after `pause()`.
    public func play() {
        control.withLock { c in
            guard c.on, !c.tearingDown, c.session != nil, c.paused else { return }
            c.paused = false
            mixer.setMaster(up: true, seconds: Self.pauseFadeSeconds)
        }
    }

    /// The output route was lost (headphones pulled): iOS moves a running engine to the speaker, so
    /// fade to silence in `routeLossFadeSeconds`, not the 1.5 s pause fade. While on, this is a pause
    /// (`play()` brings it back); during the off-fade it only hurries the fade, and the session still
    /// ends as usual. Safe from any thread: it takes only the control lock.
    public func routeLost() {
        control.withLock { c in
            guard c.session != nil, !c.tearingDown else { return }
            if c.on { c.paused = true }
            mixer.setMaster(up: false, seconds: Self.routeLossFadeSeconds)
        }
    }

    /// After `AVAudioEngineConfigurationChange` (a route or format change, an interruption): the
    /// engine has stopped itself. While the radio is on, start it again from silence: a fade in over
    /// `onFadeSeconds`, or, if paused, nothing at all until `play()`, so a pause made for a lost route
    /// is never heard fading out of the phone speaker. Off, or switching off: nothing (the render
    /// thread ends a session whose engine has stopped).
    public func restartAfterConfigurationChange() {
        control.withLock { c in
            guard c.on, c.session != nil, !c.tearingDown, !engine.isRunning else { return }
            mixer.silenceMaster()
            if !c.paused { mixer.setMaster(up: true, seconds: Self.onFadeSeconds) }
            startEngine()
        }
    }

    /// Test hook: stop the engine the way a configuration change does.
    func stopEngineForTest() { engine.stop() }

    /// Seconds of output since the radio last switched on (frames / 44100), pauses included.
    public var nowSecond: Double {
        Double(mixer.framesPlayed.load(ordering: .relaxed)) / Self.sampleRate
    }

    /// Whether the needle is out of the off zone (false from the moment the off-fade starts).
    public var isOn: Bool { control.withLock { $0.on } }

    private func switchOn(_ c: inout Control) {
        c.on = true
        c.paused = false
        // Stopping the engine right now: the teardown starts a fresh session when it is done.
        if c.tearingDown { return }
        if c.session != nil {
            // Still fading off: turn the fade around on the same session.
            mixer.offRequested.store(false, ordering: .releasing)
            mixer.fadedOut.store(false, ordering: .releasing)
            mixer.setMaster(up: true, seconds: Self.onFadeSeconds)
            if !engine.isRunning { startEngine() }
            return
        }
        // Fresh: the engine is stopped and no render thread is running, so the rings and the
        // callback state can be reset here.
        let seed = UInt64.random(in: .min ... .max)
        let clock = makeClock(seed)
        for r in mixer.rings { r.reset() }
        mixer.prepareFresh()
        mixer.setMaster(up: true, seconds: Self.onFadeSeconds)
        c.generation += 1
        let generation = c.generation
        let filler = makeFiller(seed, clock)
        var thread: RenderThread?
        if !manual {
            let t = RenderThread(rings: mixer.rings, target: Self.renderAheadFrames, filler: filler,
                                 onIdle: { [weak self] in self?.finishOffIfFaded(generation) ?? true })
            t.start()
            thread = t
        }
        c.session = Session(generation: generation, clock: clock, filler: filler, thread: thread)
        startEngine()
    }

    private func startEngine() {
        do {
            try engine.start()
        } catch {
            // Nothing that goes wrong makes a sound: stay silent. Switching off still ends the
            // session (a stopped engine counts as faded out).
            NSLog("NightRadio: AVAudioEngine failed to start: \(error)")
        }
    }

    /// Render-thread side (or `renderManually`): when the off-fade has reached silence, stop the
    /// engine, empty the rings and end the session. Returns whether the caller's session is over.
    /// `engine.stop()` (tens of ms) runs outside the lock so a dragging UI is never held up; a switch-on
    /// meanwhile is deferred and started fresh here once the old session is gone.
    private func finishOffIfFaded(_ generation: Int) -> Bool {
        let stop = control.withLock { c -> Bool? in
            guard let s = c.session, s.generation == generation, !c.tearingDown else { return true }
            // A stopped engine (failed to start, or stopped under us) has no callback to finish the fade.
            guard mixer.fadedOut.load(ordering: .acquiring) || (!c.on && !engine.isRunning) else { return false }
            guard !c.on else {
                mixer.fadedOut.store(false, ordering: .releasing)
                return false
            }
            c.tearingDown = true
            return nil
        }
        if let done = stop { return done }
        engine.stop()
        control.withLock { c in
            for r in mixer.rings { r.reset() }
            c.session = nil
            c.tearingDown = false
            if c.on { switchOn(&c) }
        }
        return true
    }

    // MARK: Manual rendering (tests)

    /// Test hook (manual rendering mode): render `frames` of output (the left channel).
    public func renderManually(frames: Int) throws -> [Float] {
        try renderManuallyStereo(frames: frames).left
    }

    struct NotManual: Error {}
    struct RenderFailed: Error { let status: AVAudioEngineManualRenderingStatus }

    func renderManuallyStereo(frames: Int) throws -> (left: [Float], right: [Float]) {
        guard manual else { throw NotManual() }
        if let e = manualSetupError { throw e }
        var left = [Float](), right = [Float]()
        left.reserveCapacity(frames)
        right.reserveCapacity(frames)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat,
                                            frameCapacity: AVAudioFrameCount(Self.manualChunkFrames)) else {
            throw NotManual()
        }
        var done = 0
        while done < frames {
            let n = min(Self.manualChunkFrames, frames - done)
            let session = control.withLock { $0.session }
            guard let s = session else {
                left.append(contentsOf: repeatElement(0, count: n))
                right.append(contentsOf: repeatElement(0, count: n))
                done += n
                continue
            }
            while s.filler.fillRound(mixer.rings, target: Self.renderAheadFrames) {}
            let status = try engine.renderOffline(AVAudioFrameCount(n), to: buffer)
            guard status == .success, let ch = buffer.floatChannelData else { throw RenderFailed(status: status) }
            let got = Int(buffer.frameLength)
            let rightCh = buffer.format.channelCount > 1 ? ch[1] : ch[0]
            left.append(contentsOf: UnsafeBufferPointer(start: ch[0], count: got))
            right.append(contentsOf: UnsafeBufferPointer(start: rightCh, count: got))
            done += got
            _ = finishOffIfFaded(s.generation)
        }
        return (left, right)
    }
}

/// Everything the audio callback touches. The UI side writes only the atomics (and, while the
/// engine is stopped, `prepareFresh`); the callback owns the rest. Preallocated; `render` never
/// allocates or locks.
final class Mixer: @unchecked Sendable {
    /// Placeholders (docs/project-state.md, "Plan 9", Task 8).
    static let gainSmoothingSeconds = 0.03
    static let underrunFadeSeconds = 0.005

    let rings: [SPSCRing]
    let needleBits = Atomic<UInt64>(0)
    let offRequested = Atomic<Bool>(false)
    let fadedOut = Atomic<Bool>(false)
    let framesPlayed = Atomic<Int>(0)
    private let gain0 = Atomic<UInt32>(0), gain1 = Atomic<UInt32>(0), gain2 = Atomic<UInt32>(0)
    private let gain3 = Atomic<UInt32>(0)
    private let masterUp = Atomic<Bool>(false)
    private let masterStepBits = Atomic<UInt32>(0)

    private let ringCount: Int
    private let maxChunk: Int
    private let smoothCoef: Float
    private let fadeFrames: Int
    // Callback-only state, preallocated.
    private let scratch: UnsafeMutablePointer<Float>
    private let mix: UnsafeMutablePointer<Float>
    private let smoothed: UnsafeMutablePointer<Float>
    private let targets: UnsafeMutablePointer<Float>
    private let playing: UnsafeMutablePointer<Bool>
    private let fadeInDone: UnsafeMutablePointer<Int>
    private let untilFadeOut: UnsafeMutablePointer<Int>
    private let fadeOutLeft: UnsafeMutablePointer<Int>
    private var masterPhase: Float = 0

    init(rings: [SPSCRing], sampleRate: Double, maxChunk: Int) {
        precondition(rings.count == 4, "three stations and the static")
        self.rings = rings
        ringCount = rings.count
        self.maxChunk = maxChunk
        smoothCoef = Float(1 - exp(-1 / (Self.gainSmoothingSeconds * sampleRate)))
        fadeFrames = max(1, Int((Self.underrunFadeSeconds * sampleRate).rounded()))
        scratch = .allocate(capacity: maxChunk)
        mix = .allocate(capacity: maxChunk)
        smoothed = .allocate(capacity: ringCount)
        targets = .allocate(capacity: ringCount)
        playing = .allocate(capacity: ringCount)
        fadeInDone = .allocate(capacity: ringCount)
        untilFadeOut = .allocate(capacity: ringCount)
        fadeOutLeft = .allocate(capacity: ringCount)
        scratch.initialize(repeating: 0, count: maxChunk)
        mix.initialize(repeating: 0, count: maxChunk)
        smoothed.initialize(repeating: 0, count: ringCount)
        targets.initialize(repeating: 0, count: ringCount)
        playing.initialize(repeating: false, count: ringCount)
        fadeInDone.initialize(repeating: 0, count: ringCount)
        untilFadeOut.initialize(repeating: 0, count: ringCount)
        fadeOutLeft.initialize(repeating: 0, count: ringCount)
    }

    deinit {
        for p in [scratch, mix, smoothed, targets] { p.deallocate() }
        playing.deallocate()
        for p in [fadeInDone, untilFadeOut, fadeOutLeft] { p.deallocate() }
    }

    private func gainAtomic(_ i: Int) -> Float {
        let bits: UInt32
        switch i {
        case 0: bits = gain0.load(ordering: .relaxed)
        case 1: bits = gain1.load(ordering: .relaxed)
        case 2: bits = gain2.load(ordering: .relaxed)
        default: bits = gain3.load(ordering: .relaxed)
        }
        return Float(bitPattern: bits)
    }

    /// UI side: the dial's gains (stations in `StationRecipe.all` order, then the static).
    func publish(stations: [Double], staticGain: Double) {
        func at(_ i: Int) -> Float { stations.indices.contains(i) ? Float(stations[i]) : 0 }
        gain0.store(at(0).bitPattern, ordering: .relaxed)
        gain1.store(at(1).bitPattern, ordering: .relaxed)
        gain2.store(at(2).bitPattern, ordering: .relaxed)
        gain3.store(Float(staticGain).bitPattern, ordering: .relaxed)
    }

    /// UI side: fade the master toward 1 or 0 over `seconds`.
    func setMaster(up: Bool, seconds: Double) {
        masterStepBits.store(Float(1 / (seconds * RadioEngine.sampleRate)).bitPattern, ordering: .relaxed)
        masterUp.store(up, ordering: .releasing)
    }

    /// UI side, engine stopped: a fresh session starts silent, at frame 0, at the published gains,
    /// with every ring waiting for its first block.
    func prepareFresh() {
        framesPlayed.store(0, ordering: .relaxed)
        offRequested.store(false, ordering: .relaxed)
        fadedOut.store(false, ordering: .relaxed)
        masterPhase = 0
        for i in 0..<ringCount {
            smoothed[i] = gainAtomic(i)
            playing[i] = false
            fadeInDone[i] = 0
            untilFadeOut[i] = 0
            fadeOutLeft[i] = 0
        }
    }

    /// UI side, engine stopped: the master starts again from silence.
    func silenceMaster() { masterPhase = 0 }

    @inline(__always) private func raisedCosineUp(_ k: Int, of n: Int) -> Float {
        0.5 * (1 - cos(Float.pi * Float(k) / Float(n)))
    }

    /// The audio callback. No locks, no allocation, no I/O.
    func render(frameCount: Int, into abl: UnsafeMutablePointer<AudioBufferList>) {
        let buffers = UnsafeMutableAudioBufferListPointer(abl)
        var offset = 0
        while offset < frameCount {
            let n = min(maxChunk, frameCount - offset)
            renderChunk(n)
            for b in buffers {
                guard let data = b.mData?.assumingMemoryBound(to: Float.self) else { continue }
                (data + offset).update(from: mix, count: n)
            }
            offset += n
        }
        framesPlayed.wrappingAdd(frameCount, ordering: .relaxed)
    }

    private func renderChunk(_ n: Int) {
        for j in 0..<n { mix[j] = 0 }
        for i in 0..<ringCount {
            targets[i] = gainAtomic(i)
            readRing(i, n)
            let target = targets[i]
            var g = smoothed[i]
            for j in 0..<n {
                g += smoothCoef * (target - g)
                mix[j] += g * scratch[j]
            }
            smoothed[i] = g
        }
        let up = masterUp.load(ordering: .acquiring)
        let step = Float(bitPattern: masterStepBits.load(ordering: .relaxed))
        let off = offRequested.load(ordering: .acquiring)
        var p = masterPhase
        for j in 0..<n {
            p = up ? min(1, p + step) : max(0, p - step)
            let m = 0.5 * (1 - cos(Float.pi * p))
            mix[j] = NightFactory.masterGuard(mix[j] * m)
        }
        masterPhase = p
        if !up, off, p == 0 { fadedOut.store(true, ordering: .releasing) }
    }

    /// Ring `i`'s next `n` frames into `scratch`, with the underrun fades; zeros where it has none.
    private func readRing(_ i: Int, _ n: Int) {
        let ring = rings[i]
        let R = fadeFrames
        if !playing[i] {
            guard ring.available >= n + R else {
                for j in 0..<n { scratch[j] = 0 }
                return
            }
            playing[i] = true
            fadeInDone[i] = 0
            untilFadeOut[i] = 0
            fadeOutLeft[i] = 0
        }
        // Playing. If this block would leave less than R frames in hand, the ring is running dry:
        // play what is left, fading the last R real frames out (the invariant keeps >= R in hand).
        let a = ring.available
        if fadeOutLeft[i] == 0 && untilFadeOut[i] == 0 && a < n + R {
            let tail = min(R, a)
            untilFadeOut[i] = a - tail
            fadeOutLeft[i] = tail
            if tail == 0 { playing[i] = false; for j in 0..<n { scratch[j] = 0 }; return }
        }
        let draining = fadeOutLeft[i] > 0
        let want = draining ? min(n, untilFadeOut[i] + fadeOutLeft[i]) : n
        let got = ring.read(into: UnsafeMutableBufferPointer(start: scratch, count: want))
        for j in got..<n { scratch[j] = 0 }
        var fin = fadeInDone[i]
        var until = untilFadeOut[i]
        var left = fadeOutLeft[i]
        for j in 0..<got {
            var g: Float = 1
            if fin < R { fin += 1; g = raisedCosineUp(fin, of: R + 1) }
            if draining {
                if until > 0 {
                    until -= 1
                } else {
                    left -= 1                                   // R-1 ... 0: the last real frame is 0
                    g *= raisedCosineUp(left, of: R)
                }
            }
            scratch[j] *= g
        }
        fadeInDone[i] = fin
        if draining {
            untilFadeOut[i] = until
            fadeOutLeft[i] = left
            if until == 0 && left == 0 { playing[i] = false }
        }
    }
}
