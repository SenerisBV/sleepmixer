import Testing
import Foundation
import Synchronization
import NightPlan
import NightDSP
import AVFoundation
@testable import NightRadio

private let sr = 44100.0
private let tenMs = Int(0.010 * sr)

private func rms(_ x: ArraySlice<Float>) -> Double {
    guard !x.isEmpty else { return 0 }
    return (x.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(x.count)).squareRoot()
}

private func db(_ v: Double) -> Double { 20 * log10(max(v, 1e-12)) }

private func maxJump(_ x: ArraySlice<Float>) -> Float {
    var m: Float = 0
    var prev = x.first ?? 0
    for v in x { m = max(m, abs(v - prev)); prev = v }
    return m
}

/// The radio's rings (three stations, then the static); 4 and 5 are the window's left and right.
/// The Plan 9 stubs below fill only these, so the window rings stay empty (silent) under them.
private let radioRings = 4

/// Writes the drift into every radio ring as audio: ratchet × 0.5 at each frame's engine second.
private final class LevelFiller: RingFiller, @unchecked Sendable {
    let clock: DriftClock
    private var frames = [Int](repeating: 0, count: 4)
    private var buf = [Float](repeating: 0, count: 2048)
    init(clock: DriftClock) { self.clock = clock }

    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        var any = false
        for (i, ring) in rings.prefix(radioRings).enumerated() where ring.available < target {
            for j in 0..<2048 { buf[j] = Float(clock.level(at: Double(frames[i] + j) / sr).ratchet * 0.5) }
            _ = buf.withUnsafeBufferPointer { ring.write($0) }
            frames[i] += 2048
            any = true
        }
        return any
    }
}

private func slice(_ x: [Float], _ from: Double, _ to: Double) -> ArraySlice<Float> {
    x[Int(from * sr)..<min(x.count, Int(to * sr))]
}

/// Writes a constant into every radio ring, block by block, up to `limit` frames per ring, then nothing:
/// the render thread "falls behind" for good.
private final class StoppingFiller: RingFiller, @unchecked Sendable {
    let limit: Int
    let value: Float
    private var written = [Int](repeating: 0, count: 4)
    private let block = [Float](repeating: 0, count: 2048)

    init(limit: Int, value: Float) { self.limit = limit; self.value = value }

    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        var any = false
        let src = [Float](repeating: value, count: 2048)
        for (i, ring) in rings.prefix(radioRings).enumerated() where ring.available < target && written[i] < limit {
            let n = min(2048, limit - written[i])
            written[i] += src.withUnsafeBufferPointer { ring.write(UnsafeBufferPointer(rebasing: $0[0..<n])) }
            any = true
        }
        return any
    }
}

/// The window stub: the radio rings write `radio(frame)` (0 by default), ring 4 (window left) and
/// ring 5 (window right) write `windowL(frame)` and `windowR(frame)`, all on the session's own frame
/// count, so the output is deterministic.
private final class WindowStubFiller: RingFiller, @unchecked Sendable {
    let radio: @Sendable (Int, Int) -> Float          // (ring, frame)
    private var frames = [Int](repeating: 0, count: 6)
    private var buf = [Float](repeating: 0, count: 2048)
    init(radio: @escaping @Sendable (Int, Int) -> Float = { _, _ in 0 }) { self.radio = radio }

    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        var any = false
        for (i, ring) in rings.enumerated() where ring.available < target {
            for j in 0..<2048 {
                let f = frames[i] + j
                buf[j] = i == 4 ? windowL(f) : i == 5 ? windowR(f) : radio(i, f)
            }
            _ = buf.withUnsafeBufferPointer { ring.write($0) }
            frames[i] += 2048
            any = true
        }
        return any
    }
}

/// Known, different ramps for the window's two sides (inside the master guard's linear range).
private func windowL(_ f: Int) -> Float { 0.05 + 0.2 * Float(f % 1000) / 1000 }
private func windowR(_ f: Int) -> Float { -0.03 - 0.15 * Float(f % 700) / 700 }

/// Hands a real `Renderer` only the radio's four rings: its window rings stay empty (silent).
private final class RadioOnlyFiller: RingFiller, @unchecked Sendable {
    let inner: Renderer
    init(_ inner: Renderer) { self.inner = inner }
    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        inner.fillRound(Array(rings.prefix(radioRings)), target: target)
    }
}

/// Window rings at 0; the static ring a loud ramp that reaches the master guard's knee.
private final class ZeroWindowFiller: RingFiller, @unchecked Sendable {
    static func staticAt(_ f: Int) -> Float { -1.2 + 2.4 * Float(f % 3000) / 3000 }
    private var frames = [Int](repeating: 0, count: 6)
    private var buf = [Float](repeating: 0, count: 2048)
    func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
        var any = false
        for (i, ring) in rings.enumerated() where ring.available < target {
            for j in 0..<2048 { buf[j] = i == 3 ? Self.staticAt(frames[i] + j) : i < 3 ? 0.3 : 0 }
            _ = buf.withUnsafeBufferPointer { ring.write($0) }
            frames[i] += 2048
            any = true
        }
        return any
    }
}

/// Needle positions: off, and between Lantern (0.25) and Lesson (0.55), where only static plays.
private let off = 0.0
private let staticOnly = 0.40

@Suite(.serialized) struct RadioEngineTests {
    @Test func offIsSilent() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.setNeedle(off)
        #expect(!radio.isOn)
        let out = try radio.renderManually(frames: 44100)
        #expect(out.count == 44100)
        #expect(out.allSatisfy { $0 == 0 })
    }

    @Test func onFadesIn() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.setNeedle(staticOnly)
        #expect(radio.isOn)
        let out = try radio.renderManually(frames: Int(3.0 * sr))
        let head = db(rms(out[0..<tenMs]))
        let settled = db(rms(slice(out, 2.5, 3.0)))
        #expect(head <= settled - 20, "head \(head) dB, settled \(settled) dB")
        #expect(slice(out, 2.5, 3.0).contains { $0 != 0 })
        #expect(abs(radio.nowSecond - 3.0) < 1e-9)
    }

    @Test func offThenOnStartsFresh() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(5 * sr))
        #expect(abs(radio.nowSecond - 5) < 1e-9)
        radio.setNeedle(off)
        #expect(!radio.isOn)
        let fading = try radio.renderManually(frames: Int(2 * sr))
        #expect(rms(fading[0..<tenMs]) > 0, "the off-fade starts from where it was, not silence")
        // The off-fade's shape: a raised cosine over 1.5 s (gain ~0.65 at 0.6 s, ~0.04 at 1.3 s).
        let fullRMS = rms(slice(fading, 0, 0.2)), midRMS = rms(slice(fading, 0.5, 0.7))
        let lateRMS = rms(slice(fading, 1.2, 1.4))
        print("off-fade RMS: head \(db(fullRMS)) mid \(db(midRMS)) late \(db(lateRMS)) dB")
        #expect(midRMS < fullRMS && midRMS > 0.3 * fullRMS, "mid \(db(midRMS)) vs head \(db(fullRMS))")
        #expect(lateRMS < 0.4 * midRMS && lateRMS > 0)
        // No step anywhere in the fade beyond what the static itself does at full level.
        let steadyJump = maxJump(slice(fading, 0, 0.2))
        print("off-fade jumps: steady \(steadyJump), fade \(maxJump(fading[...]))")
        #expect(maxJump(fading[...]) <= max(0.05, steadyJump))
        #expect(slice(fading, 1.6, 2.0).allSatisfy { $0 == 0 }, "silent once the 1.5 s off-fade is done")
        #expect(radio.rings.allSatisfy { $0.available == 0 }, "rings discarded")

        radio.setNeedle(staticOnly)
        #expect(radio.isOn)
        #expect(radio.nowSecond == 0)
        let again = try radio.renderManually(frames: Int(3 * sr))
        let head = db(rms(again[0..<tenMs]))
        let settled = db(rms(slice(again, 2.5, 3.0)))
        #expect(head <= settled - 20, "head \(head) dB, settled \(settled) dB")
        #expect(abs(radio.nowSecond - 3) < 1e-9)
    }

    @Test func underrunFadesToSilence() throws {
        let limit = Int(3 * sr)
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: limit, value: 0.5) })
        radio.setNeedle(staticOnly)
        let out = try radio.renderManually(frames: Int(4 * sr))
        let fade = Int((0.005 * sr).rounded())
        // Playing before the ring runs dry, silent from the last real frame on.
        #expect(abs(out[limit - fade - 100] - 0.5) < 0.01, "\(out[limit - fade - 100])")
        // The fade is 5 ms: full level just before it, about half way through it, zero after it.
        #expect(abs(out[limit - fade - 1] - 0.5) < 0.001, "\(out[limit - fade - 1])")
        #expect(out[limit - fade / 2] > 0.2 && out[limit - fade / 2] < 0.3, "\(out[limit - fade / 2])")
        #expect(out[limit...].allSatisfy { $0 == 0 })
        // ... and it got there within 5 ms, without a jump.
        #expect(out[(limit - fade)...].allSatisfy { abs($0) <= 0.5 })
        var maxJump: Float = 0
        for i in 1..<out.count { maxJump = max(maxJump, abs(out[i] - out[i - 1])) }
        #expect(maxJump <= 0.05, "max jump \(maxJump)")
    }

    @Test func wheelTouchDeepInTheNightGlidesBack() throws {
        // The clock factory makes the switch-on touch; this one touches long before 0, so the night
        // is deep from the start (ratchet ~0.8).
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, clock in LevelFiller(clock: clock) },
                                makeClock: { seed in
                                    let c = DriftClock(seed: seed)
                                    c.touch(at: -20000)
                                    return c
                                })
        radio.setNeedle(staticOnly)
        let before = try radio.renderManually(frames: Int(3 * sr))
        let deep = before[before.count - 1]
        #expect(deep > 0.3, "deep \(deep)")
        radio.wheelTouched()
        let after = try radio.renderManually(frames: Int(7 * sr))
        // The touch fades the drift back over 4 s from wherever it was: no step, anywhere. The fade's
        // own slope is ~4e-6 per sample; touching at the audible second instead of the render position
        // steps by ~0.13 where the already-rendered 1.5 s runs out.
        let joined: [Float] = [deep] + after
        let jump = maxJump(joined[...])
        #expect(jump < 0.001, "max jump \(jump)")
        #expect(after[after.count - 1] < 0.01, "back to bedtime clarity: \(after[after.count - 1])")
    }

    @Test func backOnWithinTheOffFadeTurnsAround() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.4) })
        radio.setNeedle(staticOnly)
        let a = try radio.renderManually(frames: Int(3 * sr))
        radio.setNeedle(off)
        let b = try radio.renderManually(frames: Int(0.5 * sr))
        radio.setNeedle(staticOnly)
        #expect(radio.isOn)
        #expect(abs(radio.nowSecond - 3.5) < 1e-9, "same session: the clock was not reset")
        let c = try radio.renderManually(frames: Int(3 * sr))
        #expect(abs(radio.nowSecond - 6.5) < 1e-9)
        #expect(b[b.count - 1] < 0.4 && b[b.count - 1] > 0.1, "mid-fade \(b[b.count - 1])")
        let all = a + b + c
        #expect(maxJump(all[...]) <= 0.05, "max jump \(maxJump(all[...]))")
        #expect(abs(c[c.count - 1] - 0.4) < 0.001, "full level again: \(c[c.count - 1])")
    }

    @Test func pauseFadesOutAndPlayFadesBack() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        radio.pause()
        let paused = try radio.renderManually(frames: Int(2 * sr))
        #expect(paused[0] > 0.4)
        #expect(slice(paused, 1.6, 2.0).allSatisfy { $0 == 0 })
        #expect(radio.isOn)
        #expect(abs(radio.nowSecond - 4.5) < 1e-9, "the clock keeps running while paused")
        radio.play()
        let back = try radio.renderManually(frames: Int(2 * sr))
        #expect(back[0] < 0.01)
        #expect(abs(back[back.count - 1] - 0.5) < 0.01)
    }

    @Test func pausedRestartAfterConfigurationChangeStaysSilent() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        // A lost route: the pause lands, then the engine stops before a callback can fade it.
        radio.pause()
        radio.stopEngineForTest()
        radio.restartAfterConfigurationChange()
        let after = try radio.renderManually(frames: Int(2 * sr))
        #expect(after.allSatisfy { $0 == 0 }, "never a fade-out into the new route")
        radio.play()
        let back = try radio.renderManually(frames: Int(2 * sr))
        #expect(back[0] < 0.01)
        #expect(abs(back[back.count - 1] - 0.5) < 0.01)
    }

    @Test func restartAfterConfigurationChangeFadesBackIn() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        radio.stopEngineForTest()
        radio.restartAfterConfigurationChange()
        let after = try radio.renderManually(frames: Int(2.5 * sr))
        #expect(after[0] < 0.01, "starts from silence: \(after[0])")
        #expect(maxJump(after[...]) <= 0.01, "max jump \(maxJump(after[...]))")
        #expect(abs(after[after.count - 1] - 0.5) < 0.01)
        #expect(radio.isOn)
    }

    /// The engine is still running (the change did not stop it): nothing happens, no dip.
    @Test func restartAfterConfigurationChangeWhileRunningIsANoOp() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        radio.restartAfterConfigurationChange()
        let after = try radio.renderManually(frames: Int(0.5 * sr))
        #expect(after.allSatisfy { abs($0 - 0.5) < 0.01 }, "no dip: min \(after.min()!)")
    }

    /// Engine calls never run under the control lock, and two threads never both start the engine:
    /// many threads switching on and off, restarting, losing the route, pausing and playing at once
    /// finish (a start held under the lock against a waiting `routeLost` would hang here), and the
    /// radio still plays afterwards.
    @Test(.timeLimit(.minutes(1))) func concurrentControlCallsNeverHang() async throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(0.5 * sr))
        await withTaskGroup(of: Void.self) { group in
            for t in 0..<6 {
                group.addTask {
                    for i in 0..<300 {
                        switch (t + i) % 6 {
                        case 0: radio.setNeedle(i % 2 == 0 ? off : staticOnly)
                        case 1: radio.restartAfterConfigurationChange()
                        case 2: radio.routeLost()
                        case 3: radio.pause()
                        case 4: radio.play()
                        default:
                            radio.stopEngineForTest()
                            radio.restartAfterConfigurationChange()
                        }
                    }
                }
            }
        }
        // Settle: on, playing, the engine running.
        radio.setNeedle(staticOnly)
        radio.play()
        radio.restartAfterConfigurationChange()
        let out = try radio.renderManually(frames: Int(3 * sr))
        #expect(radio.isOn)
        #expect(abs(out[out.count - 1] - 0.5) < 0.01, "plays after the storm: \(out[out.count - 1])")
    }

    @Test func restartAfterConfigurationChangeIsANoOpWhenOff() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.restartAfterConfigurationChange()
        #expect(!radio.isOn)
        #expect(try radio.renderManually(frames: 4410).allSatisfy { $0 == 0 })
    }

    @Test func routeLostIsSilentWithinAFewHundredthsAndStaysPaused() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        radio.routeLost()
        let lost = try radio.renderManually(frames: Int(1 * sr))
        #expect(lost[0] > 0.4)
        #expect(slice(lost, 0.05, 1.0).allSatisfy { $0 == 0 }, "silent by 0.05 s")
        #expect(maxJump(lost[...]) < 0.05, "a fade, not a click: \(maxJump(lost[...]))")
        #expect(radio.isOn)
        // A configuration change while lost stays silent; play brings it back.
        radio.stopEngineForTest()
        radio.restartAfterConfigurationChange()
        #expect(try radio.renderManually(frames: Int(0.5 * sr)).allSatisfy { $0 == 0 })
        radio.play()
        let back = try radio.renderManually(frames: Int(2 * sr))
        #expect(abs(back[back.count - 1] - 0.5) < 0.01)
    }

    @Test func routeLostDuringTheOffFadeHurriesIt() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true,
                                makeFiller: { _, _ in StoppingFiller(limit: .max, value: 0.5) })
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: Int(2.5 * sr))
        radio.setNeedle(off)
        let fading = try radio.renderManually(frames: Int(0.2 * sr))
        #expect(fading[fading.count - 1] > 0.1, "still fading off")
        radio.routeLost()
        let lost = try radio.renderManually(frames: Int(0.5 * sr))
        #expect(slice(lost, 0.05, 0.5).allSatisfy { $0 == 0 }, "silent by 0.05 s")
        #expect(!radio.isOn)
        radio.setNeedle(staticOnly)            // the session ended: a fresh night fades in
        let fresh = try radio.renderManually(frames: Int(0.1 * sr))
        #expect(fresh[0] < 0.01)
    }

    /// The radio's own mono mix (the real `Renderer`, its window rings left empty) is in both channels.
    @Test func bothChannelsCarryTheMix() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { seed, clock in
            RadioOnlyFiller(Renderer(bundles: [:], seed: seed, clock: clock, sampleRate: RadioEngine.sampleRate,
                                     blockFrames: RadioEngine.blockFrames))
        })
        radio.setNeedle(staticOnly)
        let (left, right) = try radio.renderManuallyStereo(frames: Int(2.5 * sr))
        #expect(left == right)
        #expect(left.contains { $0 != 0 })
    }

    // MARK: Plan 10: the window

    /// Review Focus 2: the window does not follow the needle. On a station, on the static and between
    /// the two, the stereo output is identical, sample for sample, fade-in included.
    @Test func windowIgnoresNeedle() throws {
        let lantern = StationRecipe.all[0].dialPosition
        var outs: [(left: [Float], right: [Float])] = []
        for needle in [lantern, staticOnly, lantern + 0.06] {
            let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { _, _ in WindowStubFiller() })
            radio.setNeedle(needle)
            outs.append(try radio.renderManuallyStereo(frames: Int(3 * sr)))
        }
        #expect(outs[0].left.contains { $0 != 0 } && outs[0].right.contains { $0 != 0 }, "the window plays")
        for o in outs.dropFirst() {
            #expect(o.left == outs[0].left)
            #expect(o.right == outs[0].right)
        }
    }

    /// Left carries the window's left ring, right its right ring, each under the master fade.
    @Test func windowIsStereoInOutput() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { _, _ in WindowStubFiller() })
        radio.setNeedle(staticOnly)
        let (left, right) = try radio.renderManuallyStereo(frames: Int(3 * sr))
        // After the 2 s fade-in the master is exactly 1.
        for f in Int(2.1 * sr)..<left.count {
            #expect(left[f] == windowL(f), "left at \(f): \(left[f]) vs \(windowL(f))")
            #expect(right[f] == windowR(f), "right at \(f): \(right[f]) vs \(windowR(f))")
            if left[f] != windowL(f) || right[f] != windowR(f) { break }
        }
        // During the fade-in, both sides are scaled by the same master gain.
        let f = Int(1.0 * sr)
        let mL = left[f] / windowL(f), mR = right[f] / windowR(f)
        #expect(mL > 0.2 && mL < 0.8, "master at 1 s: \(mL)")
        #expect(abs(mL - mR) < 1e-5, "one master for both sides: \(mL) vs \(mR)")
        #expect(left[0] == 0 && right[0] == 0, "from silence")
    }

    /// Review Focus 3: switching off fades the window with the radio. The real `Renderer` on a rain night.
    @Test func offFadesWindow() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { seed, clock in
            Renderer(bundles: [:], seed: seed, clock: clock, sampleRate: RadioEngine.sampleRate,
                     blockFrames: RadioEngine.blockFrames, windowNight: .rain)
        })
        radio.setNeedle(staticOnly)
        let on = try radio.renderManuallyStereo(frames: Int(5 * sr))
        let tail = Int(4 * sr)..<on.left.count
        #expect(tail.contains { on.left[$0] != on.right[$0] }, "the window is playing, in stereo")
        radio.setNeedle(off)
        let fading = try radio.renderManuallyStereo(frames: Int(3 * sr))
        #expect(rms(fading.left[0..<tenMs]) > 0 && rms(fading.right[0..<tenMs]) > 0)
        #expect(slice(fading.left, 2.5, 3.0).allSatisfy { $0 == 0 }, "left silent")
        #expect(slice(fading.right, 2.5, 3.0).allSatisfy { $0 == 0 }, "right silent")
        #expect(radio.rings.allSatisfy { $0.available == 0 }, "every ring discarded, the window's too")
        #expect(!radio.isOn)
    }

    /// With the window rings silent, the radio's mono path is unchanged: left == right == the old
    /// mono output, guard(radio mix x master), bit for bit.
    @Test func radioUnchangedWithoutWindow() throws {
        #expect(RadioEngine(bundles: [:], manualRendering: true).rings.count == 6, "stations, static, window L, R")
        let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { _, _ in
            ZeroWindowFiller()
        })
        radio.setNeedle(staticOnly)
        let (left, right) = try radio.renderManuallyStereo(frames: Int(3 * sr))
        #expect(left == right)
        // Static gain is 1 between stations; after the fade the master is 1: out = guard(static ring).
        for f in Int(2.1 * sr)..<left.count where left[f] != NightFactory.masterGuard(ZeroWindowFiller.staticAt(f)) {
            Issue.record("frame \(f): \(left[f]) vs \(NightFactory.masterGuard(ZeroWindowFiller.staticAt(f)))")
            break
        }
        #expect(left.contains { abs($0) > 0.6 }, "the guard's knee (above -6 dBFS) is exercised")
    }

    /// A one-buffer (mono) output gets the radio plus the window's two sides averaged.
    @Test func monoOutputAveragesTheWindow() {
        let rings = (0..<6).map { _ in SPSCRing(capacity: 8192) }
        let mixer = Mixer(rings: rings, sampleRate: sr, maxChunk: 512)
        mixer.publish(stations: [0, 0, 0], staticGain: 1)
        mixer.prepareFresh()
        mixer.setMaster(up: true, seconds: 1e-9)          // full after one sample
        let values: [Float] = [0, 0, 0, 0.1, 0.3, -0.1]   // static 0.1, window L 0.3, R -0.1
        for (i, r) in rings.enumerated() {
            let src = [Float](repeating: values[i], count: 4096)
            _ = src.withUnsafeBufferPointer { r.write($0) }
        }
        let n = 1024
        let data = UnsafeMutablePointer<Float>.allocate(capacity: n)
        defer { data.deallocate() }
        let abl = AudioBufferList.allocate(maximumBuffers: 1)
        defer { free(abl.unsafeMutablePointer) }
        abl[0] = AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(n * 4), mData: data)
        mixer.render(frameCount: n, into: abl.unsafeMutablePointer)
        // Past the 5 ms ring fade-in: 0.1 + (0.3 - 0.1) / 2 = 0.2.
        #expect(abs(data[n - 1] - 0.2) < 1e-6, "\(data[n - 1])")
    }

    /// The window's two rings are one unit in the callback: when the render thread has written the left
    /// block but not yet the right (the two writes are separate), neither side starts, and from then on
    /// left and right read the same ring frame, sample for sample. A centred sound (thunder, the fire)
    /// would otherwise sit a few ms to one side all night. Likewise when the ring runs dry: both sides
    /// drain (fade out) together.
    @Test func windowSidesStayAligned() {
        let rings = (0..<6).map { _ in SPSCRing(capacity: 16384) }
        let mixer = Mixer(rings: rings, sampleRate: sr, maxChunk: 512)
        mixer.publish(stations: [0, 0, 0], staticGain: 0)
        mixer.prepareFresh()
        mixer.setMaster(up: true, seconds: 1e-9)
        // Left ring frame f holds ramp(f), right ring frame f holds -ramp(f).
        func ramp(_ f: Int) -> Float { 0.01 + 0.3 * Float(f % 997) / 997 }
        var written = [0, 0]
        func write(_ side: Int, _ count: Int) {
            let src = (written[side]..<(written[side] + count)).map { side == 0 ? ramp($0) : -ramp($0) }
            _ = src.withUnsafeBufferPointer { rings[4 + side].write($0) }
            written[side] += count
        }
        let n = 512
        let l = UnsafeMutablePointer<Float>.allocate(capacity: n), r = UnsafeMutablePointer<Float>.allocate(capacity: n)
        defer { l.deallocate(); r.deallocate() }
        let abl = AudioBufferList.allocate(maximumBuffers: 2)
        defer { free(abl.unsafeMutablePointer) }
        abl[0] = AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(n * 4), mData: l)
        abl[1] = AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(n * 4), mData: r)
        var left = [Float](), right = [Float]()
        func render() {
            mixer.render(frameCount: n, into: abl.unsafeMutablePointer)
            left.append(contentsOf: UnsafeBufferPointer(start: l, count: n))
            right.append(contentsOf: UnsafeBufferPointer(start: r, count: n))
        }
        func aligned(_ range: Range<Int>, _ what: String) {
            for j in range where right[j] != -left[j] {
                Issue.record("\(what), frame \(j): left \(left[j]), right \(right[j])")
                break
            }
        }
        // The start edge: the left block is in, the right not yet.
        write(0, 2048)
        render()
        write(1, 2048)
        for _ in 0..<3 { render() }       // both play; 512 frames left in each
        let startEdge = left.count
        // The drain edge: the next left block lands before the right one. Both sides must drain
        // together (the right has only 512 < n + R), not the right alone.
        write(0, 2048)
        render()
        write(1, 2048)
        for _ in 0..<6 { render() }       // three chunks, a fourth that drains both, then silence
        #expect(left.contains { $0 != 0 }, "the window played")
        #expect(rings[4].available == 0 && rings[5].available == 0, "both rings fully drained")
        aligned(0..<startEdge, "start edge")
        aligned(startEdge..<left.count, "drain edge")
    }

    @Test func tuningCrossfadesSmoothly() throws {
        // Ring i holds the constant i + 1 (stations 1, 2, 3, static 4) scaled down; a jump of the
        // needle from static to Lantern must glide (30 ms one-pole), not step.
        final class Constants: RingFiller, @unchecked Sendable {
            func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
                var any = false
                for (i, ring) in rings.prefix(radioRings).enumerated() where ring.available < target {
                    let src = [Float](repeating: Float(i + 1) * 0.1, count: 2048)
                    _ = src.withUnsafeBufferPointer { ring.write($0) }
                    any = true
                }
                return any
            }
        }
        let radio = RadioEngine(bundles: [:], manualRendering: true, makeFiller: { _, _ in Constants() })
        radio.setNeedle(staticOnly)
        let a = try radio.renderManually(frames: Int(2.2 * sr))
        #expect(abs(a[a.count - 1] - 0.4) < 0.001)
        radio.setNeedle(StationRecipe.all[0].dialPosition)
        let b = try radio.renderManually(frames: Int(0.3 * sr))
        #expect(abs(b[b.count - 1] - 0.1) < 0.001)
        var maxJump: Float = 0
        var prev = a[a.count - 1]
        for v in b { maxJump = max(maxJump, abs(v - prev)); prev = v }
        #expect(maxJump < 0.001, "max jump \(maxJump)")
        #expect(b[Int(0.03 * sr)] > 0.15, "a 30 ms one-pole is still a third of the way at 30 ms")
    }

    @Test func wheelTouchedIsSafeOffAndOn() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.wheelTouched()                      // off: no-op
        radio.setNeedle(staticOnly)
        _ = try radio.renderManually(frames: 4410)
        radio.wheelTouched()
        #expect(radio.isOn)
    }

    /// The engine can be freed on the render thread (its `onIdle` held the last reference); its deinit
    /// then stops the thread from the thread itself, which must not wait on itself.
    @Test(.timeLimit(.minutes(1))) func renderThreadCanStopItself() async throws {
        final class Box: @unchecked Sendable { var thread: RenderThread?; let idled = Atomic<Int>(0) }
        let box = Box()
        let rings = (0..<4).map { _ in SPSCRing(capacity: 8192) }
        let thread = RenderThread(rings: rings, target: 4096, filler: StoppingFiller(limit: 0, value: 0),
                                  onIdle: { [box] in
                                      box.idled.add(1, ordering: .relaxed)
                                      box.thread?.stop()          // from the thread itself
                                      return false
                                  })
        box.thread = thread
        thread.start()
        let deadline = ContinuousClock.now + .seconds(10)
        while box.idled.load(ordering: .relaxed) == 0, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(1))
        }
        while !thread.hasEnded, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(1))
        }
        #expect(box.idled.load(ordering: .relaxed) == 1, "it stopped itself after one idle round")
        #expect(thread.hasEnded, "the thread waited on itself")
        thread.stop()
    }

    @Test func renderThreadFillsRings() async throws {
        let rings = (0..<4).map { _ in SPSCRing(capacity: RadioEngine.ringCapacity) }
        let thread = RenderThread(rings: rings, target: RadioEngine.renderAheadFrames,
                                  filler: StoppingFiller(limit: .max, value: 0.25))
        thread.start()
        let deadline = ContinuousClock.now + .seconds(10)
        while rings.contains(where: { $0.available < RadioEngine.renderAheadFrames }), ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(5))
        }
        thread.stop()
        #expect(rings.allSatisfy { $0.available >= RadioEngine.renderAheadFrames })
        #expect(rings.allSatisfy { $0.available <= RadioEngine.ringCapacity })
    }
}
