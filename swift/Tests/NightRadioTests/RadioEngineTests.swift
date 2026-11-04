import Testing
import Foundation
import NightPlan
@testable import NightRadio

private let sr = 44100.0
private let tenMs = Int(0.010 * sr)

private func rms(_ x: ArraySlice<Float>) -> Double {
    guard !x.isEmpty else { return 0 }
    return (x.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(x.count)).squareRoot()
}

private func db(_ v: Double) -> Double { 20 * log10(max(v, 1e-12)) }

private func slice(_ x: [Float], _ from: Double, _ to: Double) -> ArraySlice<Float> {
    x[Int(from * sr)..<min(x.count, Int(to * sr))]
}

/// Writes a constant into every ring, block by block, up to `limit` frames per ring, then nothing:
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
        for (i, ring) in rings.enumerated() where ring.available < target && written[i] < limit {
            let n = min(2048, limit - written[i])
            written[i] += src.withUnsafeBufferPointer { ring.write(UnsafeBufferPointer(rebasing: $0[0..<n])) }
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
        let fade = Int(0.005 * sr)
        // Playing before the ring runs dry, silent from the last real frame on.
        #expect(abs(out[limit - fade - 100] - 0.5) < 0.01, "\(out[limit - fade - 100])")
        #expect(out[limit...].allSatisfy { $0 == 0 })
        // ... and it got there within 5 ms, without a jump.
        #expect(out[(limit - fade)...].allSatisfy { abs($0) <= 0.5 })
        var maxJump: Float = 0
        for i in 1..<out.count { maxJump = max(maxJump, abs(out[i] - out[i - 1])) }
        #expect(maxJump <= 0.05, "max jump \(maxJump)")
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

    @Test func bothChannelsCarryTheMix() throws {
        let radio = RadioEngine(bundles: [:], manualRendering: true)
        radio.setNeedle(staticOnly)
        let (left, right) = try radio.renderManuallyStereo(frames: Int(2.5 * sr))
        #expect(left == right)
        #expect(left.contains { $0 != 0 })
    }

    @Test func tuningCrossfadesSmoothly() throws {
        // Ring i holds the constant i + 1 (stations 1, 2, 3, static 4) scaled down; a jump of the
        // needle from static to Lantern must glide (30 ms one-pole), not step.
        final class Constants: RingFiller, @unchecked Sendable {
            func fillRound(_ rings: [SPSCRing], target: Int) -> Bool {
                var any = false
                for (i, ring) in rings.enumerated() where ring.available < target {
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
