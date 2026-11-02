import Foundation
import Testing
import NightPlan
@testable import NightDSP

private func render(seed: UInt64, warp: WarpDepth = .plain, from: Double = 0, seconds: Double, sr: Double = 44100) -> [Float] {
    var scene = ChimesScene(seed: seed, sampleRate: sr, warp: .constant(warp), startSecond: from)
    let n = Int(seconds * sr)
    var out = [Float](repeating: 0, count: n)
    scene.render(into: &out, count: n)
    return out
}

@Suite struct ChimesSceneTests {
    let sr = 44100.0

    @Test func elementsAreNamed() {
        let scene = ChimesScene(seed: 1, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
        #expect(scene.elements == ["strike", "body", "bloom", "beating"])
        #expect(ChimesScene.kind == .chimes)
    }

    @Test func sameSeedSameSound() {
        let a = render(seed: 7, seconds: 20)
        let b = render(seed: 7, seconds: 20)
        let c = render(seed: 8, seconds: 20)
        #expect(a == b)
        #expect(a != c)
    }

    @Test func seekIsExact() {
        let whole = render(seed: 7, seconds: 40)
        let seeked = render(seed: 7, from: 25, seconds: 15)
        let slice = Array(whole[Int(25 * sr)..<Int(40 * sr)])
        #expect(seeked.count == slice.count)
        #expect(seeked == slice)
    }

    /// Seeking past the lookback window, in uneven chunks, at maximum slowness (longest tails).
    @Test func seekIsExactLateAndChunked() {
        let warp = WarpDepth(slowness: 1)
        let whole = render(seed: 3, warp: warp, from: 100, seconds: 30)
        var scene = ChimesScene(seed: 3, sampleRate: sr, warp: .constant(warp), startSecond: 115)
        var parts: [Float] = []
        for chunk in [1, 333, 4096, 100_000, 557_070] {
            var buf = [Float](repeating: 0, count: chunk)
            scene.render(into: &buf, count: chunk)
            parts += buf
        }
        let slice = Array(whole[Int(15 * sr)..<Int(30 * sr)])
        #expect(parts.count == slice.count)
        #expect(parts == slice)
    }

    @Test func hourEightIsHealthy() {
        var early = 0.0, late = 0.0
        var latePeak: Float = 0
        var finite = true
        for seed in UInt64(1)...5 {
            let a = render(seed: seed, seconds: 60)
            let b = render(seed: seed, from: 28_800, seconds: 60)
            finite = finite && b.allSatisfy { $0.isFinite }
            early += Analysis.rmsDB(a[...]) / 5
            late += Analysis.rmsDB(b[...]) / 5
            latePeak = max(latePeak, b.map { abs($0) }.max() ?? 0)
        }
        #expect(finite)
        #expect(abs(late - early) < 6)
        #expect(latePeak <= 1)
    }

    @Test func slownessThinsAndLowers() {
        var plainCount = 0, slowCount = 0
        var plainCentroid = 0.0, slowCentroid = 0.0
        let slow = WarpDepth(slowness: 1)
        for seed in UInt64(1)...5 {
            plainCount += ChimesScene.strikeTimes(seed: seed, sampleRate: sr, warp: .constant(.plain), from: 0, to: 120).count
            slowCount += ChimesScene.strikeTimes(seed: seed, sampleRate: sr, warp: .constant(slow), from: 0, to: 120).count
            plainCentroid += Analysis.centroidHz(render(seed: seed, seconds: 120), sampleRate: sr)
            slowCentroid += Analysis.centroidHz(render(seed: seed, warp: slow, seconds: 120), sampleRate: sr)
        }
        #expect(plainCount > 0)
        #expect(Double(slowCount) <= 0.6 * Double(plainCount))
        #expect(slowCentroid < plainCentroid)
    }

    /// Guards the pitch drop directly: the centroid test can pass on density and decay alone.
    @Test func slownessLowersPitchByThreeSemitones() {
        for seed in UInt64(1)...5 {
            for cell in [0, 1, 7, 42, 13_000] {
                let plain = ChimesScene.fundamental(seed: seed, cell: cell, warp: .plain)
                let slow = ChimesScene.fundamental(seed: seed, cell: cell, warp: WarpDepth(slowness: 1))
                #expect(plain >= 196 && plain < 392 * 4)
                #expect(abs(slow / plain - pow(2, -3.0 / 12)) < 1e-9)
            }
        }
    }

    @Test func proportionReweights() {
        let full = Curve.constant(WarpDepth(proportion: 1))
        for i in UInt64(0)..<40 {
            let gains = ChimesScene.elementGains(seed: 7, index: i, warp: full)
            #expect(gains.count == 4)
            #expect(gains.filter { $0 == 6 }.count == 1)
            #expect(gains.filter { $0 == -12 }.count == 3)
            #expect(ChimesScene.elementGains(seed: 7, index: i, warp: .constant(.plain)) == [0, 0, 0, 0])
        }
    }

    @Test func strikeAttackIsSoft() {
        #expect(ChimesScene.strikeAttack >= 0.02)
        for t in [-0.01, 0, 0.005, 0.01, 0.019, 0.02, 0.05, 0.3] {
            #expect(ChimesScene.strikeEnvelope(t: t)
                == Envelope.attackDecay(t: t, attack: ChimesScene.strikeAttack, decay: ChimesScene.strikeDecay))
        }
    }

    @Test func listeningSample() {
        writeIfListening(render(seed: 7, seconds: 60), name: "chimes-plain", sr: sr)
    }

    @Test func nothingAbove6k() {
        let x = render(seed: 7, seconds: 60)
        #expect(Analysis.bandEnergyRatio(x, sampleRate: sr, above: 6000) < 0.05)
    }
}
