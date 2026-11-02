import Foundation
import Testing
import NightPlan
@testable import NightDSP

private func render(
    seed: UInt64, warp: WarpDepth = .plain, from: Double = 0, seconds: Double,
    sr: Double = 44100, pixellate: Bool = true
) -> [Float] {
    var scene = WavesScene(seed: seed, sampleRate: sr, warp: .constant(warp), startSecond: from)
    scene.pixellate = pixellate
    let n = Int(seconds * sr)
    var out = [Float](repeating: 0, count: n)
    scene.render(into: &out, count: n)
    return out
}

@Suite struct WavesSceneTests {
    let sr = 44100.0

    @Test func elementsAreNamed() {
        let scene = WavesScene(seed: 1, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
        #expect(scene.elements == ["swell", "break", "wash"])
        #expect(WavesScene.kind == .waves)
    }

    @Test func sameSeedSameSound() {
        let a = render(seed: 7, seconds: 20)
        let b = render(seed: 7, seconds: 20)
        let c = render(seed: 8, seconds: 20)
        #expect(a == b)
        #expect(a != c)
    }

    @Test func seekIsClose() {
        let whole = render(seed: 7, seconds: 40)
        let seeked = seekLeadIn({ WavesScene(seed: 7, sampleRate: sr, warp: .constant(.plain), startSecond: $0) },
                                from: 25, seconds: 15, sr: sr)
        let slice = Array(whole[Int(25 * sr)..<Int(40 * sr)])
        #expect(seeked.count == slice.count)
        let diff = zip(seeked, slice).map { $0 - $1 }
        let signal = Analysis.rmsDB(slice[...])
        #expect(signal > -60)
        #expect(Analysis.rmsDB(diff[...]) <= signal - 40)
    }

    /// Every wave runs its filters from its own birth and the hold is keyed to absolute frames,
    /// so once the 6 s lead-in has settled the output lowpass, a seek matches bit for bit.
    @Test func seekWithLeadInIsExact() {
        let cases: [(Double, WarpDepth)] = [(25, .plain), (137.3, WarpDepth(slowness: 1)),
                                            (28_811, WarpDepth(slowness: 0.5, proportion: 1))]
        for seed in UInt64(1)...5 {
            for (from, warp) in cases {
                let whole = render(seed: seed, warp: warp, from: from - 10, seconds: 25)
                let seeked = seekLeadIn({ WavesScene(seed: seed, sampleRate: sr, warp: .constant(warp), startSecond: $0) },
                                        from: from, seconds: 15, sr: sr)
                #expect(seeked == Array(whole[Int(10 * sr)..<Int(25 * sr)]))
            }
        }
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

    /// Peak safety as a bound, not a sample of seeds: the worst summed envelope any night can
    /// reach, times the L1 norm of the output lowpass, stays at or under 0.9 (-1 dB margin).
    @Test(arguments: [44100.0, 48000.0]) func peakIsBounded(sr: Double) {
        var lp = WavesScene.outputFilter(sampleRate: sr)
        var l1 = 0.0
        for k in 0..<16_384 { l1 += abs(Double(lp.process(k == 0 ? 1 : 0))) }
        let worst = WavesScene.worstEnvelope()
        #expect(l1 > 1)
        #expect(worst * l1 <= 0.9)
    }

    /// The bound really bounds: no sampled envelope at any warp corner exceeds it.
    @Test func worstEnvelopeBoundsRealNights() {
        let worst = WavesScene.worstEnvelope()
        var seen = 0.0
        for seed in UInt64(1)...20 {
            for warp in [WarpDepth.plain, WarpDepth(slowness: 1, proportion: 1), WarpDepth(slowness: 0.5, proportion: 1)] {
                let scene = WavesScene(seed: seed, sampleRate: sr, warp: .constant(warp), startSecond: 0)
                for k in 0..<6000 { seen = max(seen, scene.envelope(at: Double(k) * 0.05)) }
            }
        }
        #expect(seen > 0.5 * worst)
        #expect(seen <= worst)
    }

    @Test func slownessLengthensWaves() {
        func meanLength(_ w: WarpDepth) -> Double {
            var total = 0.0, count = 0
            for seed in UInt64(1)...5 {
                for span in WavesScene.waveSpans(seed: seed, warp: .constant(w), from: 0, to: 300) {
                    total += span.upperBound - span.lowerBound
                    count += 1
                }
            }
            return count > 0 ? total / Double(count) : 0
        }
        let plain = meanLength(.plain)
        #expect(plain > 0)
        #expect(meanLength(WarpDepth(slowness: 1)) >= 1.8 * plain)
    }

    /// Guards against the pixellation chain silently doing nothing (the 4 kHz lowpass stays in
    /// both renders, so only normalise, sample-and-hold and quantise can move the ratio).
    @Test func pixellationIsAudible() {
        let on = render(seed: 7, seconds: 60)
        let off = render(seed: 7, seconds: 60, pixellate: false)
        let a = Analysis.bandEnergyRatio(on, sampleRate: sr, above: 2800)
        let b = Analysis.bandEnergyRatio(off, sampleRate: sr, above: 2800)
        #expect(b > 0)
        #expect(abs(a - b) > 0.1 * b)
    }

    /// Guards the quantiser directly: `pixellationIsAudible` can pass on the sample-and-hold alone.
    @Test func quantiserHasSevenBits() {
        var levels = Set<Float>()
        for k in -20_000...20_000 {
            levels.insert(WavesScene.quantise(Double(k) / 10_000))
        }
        #expect(levels.count <= 128)
        #expect(levels.count >= 100)
        #expect(WavesScene.quantise(0) == 0)
        #expect(levels.allSatisfy { abs($0) <= 1 })
    }

    @Test func listeningSample() {
        writeIfListening(render(seed: 7, seconds: 60), name: "waves-plain", sr: sr)
    }

    /// Where the wave envelope is below -40 dBFS but alive, the render stays below -34 dBFS
    /// (briefed). It also follows the envelope down rather than being gated off: quantising
    /// before normalising turns quiet passages to silence, which the -34 dBFS bound can't see.
    @Test func noGatedCrunch() {
        let window = Int(0.05 * sr), probe = Int(0.01 * sr)
        var quiet = 0, loud = 0, gated = 0
        for seed in UInt64(1)...5 {
            let scene = WavesScene(seed: seed, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
            let x = render(seed: seed, seconds: 120)
            for w in stride(from: 0, to: x.count - window, by: window) {
                let env = stride(from: w, through: w + window, by: probe).map { scene.envelope(at: Double($0) / sr) }
                guard let top = env.max(), top > 0, top < 0.01 else { continue }
                quiet += 1
                let level = Analysis.rmsDB(x[w..<(w + window)])
                if level >= -34 { loud += 1 }
                let envDB = 10 * log10(env.map { $0 * $0 }.reduce(0, +) / Double(env.count))
                if level < envDB - 40 || level > envDB { gated += 1 }
            }
        }
        #expect(quiet > 0)
        #expect(loud == 0)
        #expect(gated == 0)
    }

    /// Without a lead-in, only the output lowpass and the first hold start cold: each wave
    /// already under way runs its own filters from its birth.
    @Test func coldSeekIsNearlyExact() {
        let whole = render(seed: 7, seconds: 40)
        let cold = render(seed: 7, from: 25, seconds: 15)
        let slice = Array(whole[Int(25 * sr)..<Int(40 * sr)])
        let diff = zip(cold, slice).map { $0 - $1 }
        #expect(Analysis.rmsDB(diff[...]) <= Analysis.rmsDB(slice[...]) - 55)
    }
}
