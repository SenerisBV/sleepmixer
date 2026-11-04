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
/// `Mutex` that the audio callback never touches. No `AVAudioEngine` call (`start`, `stop`, not even
/// `isRunning`) is made while that lock is held: decide under the lock, call the engine outside it,
/// then lock again to commit. So `routeLost()`, which may run on any thread, never waits on the engine.
///
/// **Starting and stopping the engine.** Two flags in `Control` are the engine token; at most one is
/// set, and only its holder calls `start()` / `stop()`:
/// - `tearingDown`: the render thread (or `renderManually`) is stopping the engine at the end of an
///   off-fade. Starts are refused meanwhile; a switch-on is deferred and started when it is done.
/// - `starting`: some thread is in `startEngineIfWanted`. A teardown waits for it (the render
///   thread asks again 5 ms later); another start request sets `startAgain`, and the holder checks
///   again once it has committed, so a configuration change right after a start is never lost.
/// `startEpoch` counts claimed starts, so a teardown that read `isRunning` outside the lock can tell
/// that a start slipped in between and must not stop a freshly started engine mid-fade. `setNeedle` computes `Dial.gains` there (it
/// allocates) and publishes the four gains as `Atomic<UInt32>` Float bit patterns. The render thread
/// owns the chains and writes the rings. The audio callback (`Mixer.render`) reads the rings and the
/// atomics only: no locks, no allocation, no I/O.
///
/// **The callback.** Each ring's gain is smoothed per sample by a 30 ms one-pole; the master fade is a
/// raised cosine of a linear phase that moves at 1 / (fade seconds × 44100) per sample toward its
/// target, so a fade reversed midway turns around without a step. The output is stereo,
/// non-interleaved Float32 at 44100 Hz.
///
/// **The window (Plan 10).** Six rings: 0-2 the stations, 3 the static, 4 and 5 the window's left and
/// right (`WindowChain`, already at its final level). The radio's four rings make a mono mix as
/// before; the window rings have a fixed gain of 1 (no atomic, nothing from the dial, so the window is
/// the same on a station, on the static and between) and take the same underrun fades. Then, under
/// the one master fade (so switching off fades the window too): left = guard((radio + window L) x
/// master), right = guard((radio + window R) x master). With the window rings silent this is the
/// Plan 9 mono output, bit for bit. A one-buffer (mono) output gets guard((radio + (L + R) / 2) x
/// master); any buffer past the second gets the same as the first.
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
        /// A thread is starting the engine outside the lock (`startEngineIfWanted`).
        var starting = false
        /// A start was asked for while `starting`: the holder checks again before letting go.
        var startAgain = false
        /// Incremented each time a thread claims `starting`.
        var startEpoch = 0
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
        let mixer = Mixer(rings: (0..<Mixer.ringCount).map { _ in SPSCRing(capacity: Self.ringCapacity) },
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
        let start = control.withLock { c -> Bool in
            // Off-zone gains (all zero) are not published: the off-fade keeps the last sound.
            if g.isOn { mixer.publish(stations: g.stations, staticGain: g.staticGain) }
            if g.isOn && !c.on {
                return switchOn(&c)
            } else if !g.isOn && c.on {
                c.on = false
                c.paused = false
                if c.session != nil {
                    mixer.offRequested.store(true, ordering: .releasing)
                    mixer.setMaster(up: false, seconds: Self.offFadeSeconds)
                }
            }
            return false
        }
        if start { startEngineIfWanted() }
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
    /// ends as usual. Safe from any thread: it takes only the control lock, which is never held across
    /// an engine call, so it never waits on `AVAudioEngine`.
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
        startEngineIfWanted()
    }

    /// Test hook: stop the engine the way a configuration change does.
    func stopEngineForTest() { engine.stop() }

    /// Seconds of output since the radio last switched on (frames / 44100), pauses included.
    public var nowSecond: Double {
        Double(mixer.framesPlayed.load(ordering: .relaxed)) / Self.sampleRate
    }

    /// Whether the needle is out of the off zone (false from the moment the off-fade starts).
    public var isOn: Bool { control.withLock { $0.on } }

    /// Under the lock. Returns whether the caller must call `startEngineIfWanted()` once it has
    /// let go of the lock.
    private func switchOn(_ c: inout Control) -> Bool {
        c.on = true
        c.paused = false
        // Stopping the engine right now: the teardown starts a fresh session when it is done.
        if c.tearingDown { return false }
        if c.session != nil {
            // Still fading off: turn the fade around on the same session (and start the engine if it
            // has stopped under us; the start path brings it back from silence).
            mixer.offRequested.store(false, ordering: .releasing)
            mixer.fadedOut.store(false, ordering: .releasing)
            mixer.setMaster(up: true, seconds: Self.onFadeSeconds)
            return true
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
        return true
    }

    /// Starts the engine if the radio wants it running (on, a session, not tearing down) and it is
    /// stopped. Synchronous, on the calling thread, with the control lock held only around the
    /// decisions:
    /// 1. Lock: claim `starting` (or, if another thread holds it, set `startAgain` and leave).
    /// 2. Unlocked: read `engine.isRunning`. Running: nothing to do.
    /// 3. Lock: still on? Then the master starts again from silence and fades in over
    ///    `onFadeSeconds`, or stays silent if paused (until `play()`). The engine is stopped and no one
    ///    else may start it, so the callback state is ours to set.
    /// 4. Unlocked: `engine.start()`.
    /// 5. Lock: let go of `starting`; if `startAgain` was set meanwhile, go round again.
    private func startEngineIfWanted() {
        while true {
            let claimed = control.withLock { c -> Bool in
                guard c.on, c.session != nil, !c.tearingDown else { return false }
                guard !c.starting else {
                    c.startAgain = true
                    return false
                }
                c.starting = true
                c.startAgain = false
                c.startEpoch &+= 1
                return true
            }
            guard claimed else { return }
            if !engine.isRunning {
                let go = control.withLock { c -> Bool in
                    // Switched off meanwhile: a stopped engine counts as faded out; the teardown ends it.
                    guard c.on else { return false }
                    mixer.silenceMaster()
                    if !c.paused { mixer.setMaster(up: true, seconds: Self.onFadeSeconds) }
                    return true
                }
                if go { startEngine() }
            }
            let again = control.withLock { c -> Bool in
                c.starting = false
                defer { c.startAgain = false }
                return c.startAgain
            }
            guard again else { return }
        }
    }

    /// Only from `startEngineIfWanted`, holding `starting`, outside the lock.
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
    ///
    /// `engine.isRunning` is read outside the lock too: the first look notes `startEpoch`, and the
    /// commit refuses if a start is in flight or was claimed since (it asks again next idle round).
    private func finishOffIfFaded(_ generation: Int) -> Bool {
        let look = control.withLock { c -> (done: Bool?, epoch: Int) in
            guard let s = c.session, s.generation == generation, !c.tearingDown else { return (true, 0) }
            // Playing: the common idle case; nothing to read.
            if c.on && !mixer.fadedOut.load(ordering: .acquiring) { return (false, 0) }
            return (nil, c.startEpoch)
        }
        if let done = look.done { return done }
        let running = engine.isRunning
        let stop = control.withLock { c -> Bool? in
            guard let s = c.session, s.generation == generation, !c.tearingDown else { return true }
            // A start in flight or slipped in since `running` was read: not now.
            guard !c.starting, c.startEpoch == look.epoch else { return false }
            // A stopped engine (failed to start, or stopped under us) has no callback to finish the fade.
            guard mixer.fadedOut.load(ordering: .acquiring) || (!c.on && !running) else { return false }
            guard !c.on else {
                mixer.fadedOut.store(false, ordering: .releasing)
                return false
            }
            c.tearingDown = true
            return nil
        }
        if let done = stop { return done }
        engine.stop()
        let start = control.withLock { c -> Bool in
            for r in mixer.rings { r.reset() }
            c.session = nil
            c.tearingDown = false
            return c.on ? switchOn(&c) : false
        }
        if start { startEngineIfWanted() }
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

    /// Ring layout: three stations, the static, then the window's left and right.
    static let radioRingCount = 4, windowLeftRing = 4, windowRightRing = 5, ringCount = 6

    let rings: [SPSCRing]
    let needleBits = Atomic<UInt64>(0)
    let offRequested = Atomic<Bool>(false)
    let fadedOut = Atomic<Bool>(false)
    let framesPlayed = Atomic<Int>(0)
    private let gain0 = Atomic<UInt32>(0), gain1 = Atomic<UInt32>(0), gain2 = Atomic<UInt32>(0)
    private let gain3 = Atomic<UInt32>(0)
    private let masterUp = Atomic<Bool>(false)
    private let masterStepBits = Atomic<UInt32>(0)

    private let maxChunk: Int
    private let smoothCoef: Float
    private let fadeFrames: Int
    // Callback-only state, preallocated.
    private let scratch: UnsafeMutablePointer<Float>
    private let mix: UnsafeMutablePointer<Float>
    /// The window's two sides for this chunk; after `renderChunk`, the finished left and right.
    private let windowL: UnsafeMutablePointer<Float>
    private let windowR: UnsafeMutablePointer<Float>
    private let smoothed: UnsafeMutablePointer<Float>
    private let targets: UnsafeMutablePointer<Float>
    private let playing: UnsafeMutablePointer<Bool>
    private let fadeInDone: UnsafeMutablePointer<Int>
    private let untilFadeOut: UnsafeMutablePointer<Int>
    private let fadeOutLeft: UnsafeMutablePointer<Int>
    private var masterPhase: Float = 0

    init(rings: [SPSCRing], sampleRate: Double, maxChunk: Int) {
        precondition(rings.count == Self.ringCount, "three stations, the static, the window's left and right")
        self.rings = rings
        self.maxChunk = maxChunk
        smoothCoef = Float(1 - exp(-1 / (Self.gainSmoothingSeconds * sampleRate)))
        fadeFrames = max(1, Int((Self.underrunFadeSeconds * sampleRate).rounded()))
        scratch = .allocate(capacity: maxChunk)
        mix = .allocate(capacity: maxChunk)
        windowL = .allocate(capacity: maxChunk)
        windowR = .allocate(capacity: maxChunk)
        smoothed = .allocate(capacity: Self.ringCount)
        targets = .allocate(capacity: Self.ringCount)
        playing = .allocate(capacity: Self.ringCount)
        fadeInDone = .allocate(capacity: Self.ringCount)
        untilFadeOut = .allocate(capacity: Self.ringCount)
        fadeOutLeft = .allocate(capacity: Self.ringCount)
        scratch.initialize(repeating: 0, count: maxChunk)
        mix.initialize(repeating: 0, count: maxChunk)
        windowL.initialize(repeating: 0, count: maxChunk)
        windowR.initialize(repeating: 0, count: maxChunk)
        smoothed.initialize(repeating: 0, count: Self.ringCount)
        targets.initialize(repeating: 0, count: Self.ringCount)
        playing.initialize(repeating: false, count: Self.ringCount)
        fadeInDone.initialize(repeating: 0, count: Self.ringCount)
        untilFadeOut.initialize(repeating: 0, count: Self.ringCount)
        fadeOutLeft.initialize(repeating: 0, count: Self.ringCount)
    }

    deinit {
        for p in [scratch, mix, windowL, windowR, smoothed, targets] { p.deallocate() }
        playing.deallocate()
        for p in [fadeInDone, untilFadeOut, fadeOutLeft] { p.deallocate() }
    }

    private func gainAtomic(_ i: Int) -> Float {
        let bits: UInt32
        switch i {
        case 0: bits = gain0.load(ordering: .relaxed)
        case 1: bits = gain1.load(ordering: .relaxed)
        case 2: bits = gain2.load(ordering: .relaxed)
        case 3: bits = gain3.load(ordering: .relaxed)
        default: return 1                                   // the window: fixed, the dial has no say
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
        for i in 0..<Self.ringCount {
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
        let stereo = buffers.count > 1
        var offset = 0
        while offset < frameCount {
            let n = min(maxChunk, frameCount - offset)
            renderChunk(n, stereo: stereo)
            for (k, b) in buffers.enumerated() {
                guard let data = b.mData?.assumingMemoryBound(to: Float.self) else { continue }
                (data + offset).update(from: stereo ? (k == 1 ? windowR : windowL) : mix, count: n)
            }
            offset += n
        }
        framesPlayed.wrappingAdd(frameCount, ordering: .relaxed)
    }

    /// Stereo: the finished left and right land in `windowL` and `windowR`. Mono: in `mix`.
    private func renderChunk(_ n: Int, stereo: Bool) {
        for j in 0..<n { mix[j] = 0 }
        for i in 0..<Self.radioRingCount {
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
        // The window: gain 1, so its rings go straight in (the underrun fades still apply). The two
        // rings are one unit: both decide from the smaller `available`, read once, so a left block
        // written a moment before its right one never starts (or drains) one side a chunk early and
        // leaves the two offset for the rest of the night. Both rings hold at least this much.
        let pair = min(rings[Self.windowLeftRing].available, rings[Self.windowRightRing].available)
        readRing(Self.windowLeftRing, n, available: pair)
        windowL.update(from: scratch, count: n)
        readRing(Self.windowRightRing, n, available: pair)
        windowR.update(from: scratch, count: n)
        let up = masterUp.load(ordering: .acquiring)
        let step = Float(bitPattern: masterStepBits.load(ordering: .relaxed))
        let off = offRequested.load(ordering: .acquiring)
        var p = masterPhase
        if stereo {
            for j in 0..<n {
                p = up ? min(1, p + step) : max(0, p - step)
                let m = 0.5 * (1 - cos(Float.pi * p))
                windowL[j] = NightFactory.masterGuard((mix[j] + windowL[j]) * m)
                windowR[j] = NightFactory.masterGuard((mix[j] + windowR[j]) * m)
            }
        } else {
            for j in 0..<n {
                p = up ? min(1, p + step) : max(0, p - step)
                let m = 0.5 * (1 - cos(Float.pi * p))
                mix[j] = NightFactory.masterGuard((mix[j] + 0.5 * (windowL[j] + windowR[j])) * m)
            }
        }
        masterPhase = p
        if !up, off, p == 0 { fadedOut.store(true, ordering: .releasing) }
    }

    /// Ring `i`'s next `n` frames into `scratch`, with the underrun fades; zeros where it has none.
    /// `available`, when given, stands in for the ring's own count in every decision (the window's
    /// pair passes their common minimum); it must not exceed what the ring holds.
    private func readRing(_ i: Int, _ n: Int, available given: Int? = nil) {
        let ring = rings[i]
        let R = fadeFrames
        if !playing[i] {
            guard (given ?? ring.available) >= n + R else {
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
        let a = given ?? ring.available
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
