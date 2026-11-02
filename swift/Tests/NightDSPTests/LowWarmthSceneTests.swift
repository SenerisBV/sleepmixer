import Foundation
import Testing
import NightPlan
@testable import NightDSP

private func render(seed: UInt64, warp: WarpDepth = .plain, from: Double = 0, seconds: Double, sr: Double = 44100) -> [Float] {
    var scene = LowWarmthScene(seed: seed, sampleRate: sr, warp: .constant(warp), startSecond: from)
    let n = Int(seconds * sr)
    var out = [Float](repeating: 0, count: n)
    scene.render(into: &out, count: n)
    return out
}

private func hz(midi: Int) -> Double { 440 * pow(2, Double(midi - 69) / 12) }

@Suite struct LowWarmthSceneTests {
    let sr = 44100.0

    @Test func elementsAreNamed() {
        let scene = LowWarmthScene(seed: 1, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
        #expect(scene.elements == ["root", "fifth", "third"])
        #expect(LowWarmthScene.kind == .warmth)
        #expect(LowWarmthScene.cellSeconds == 12)
        #expect(LowWarmthScene.swellSeconds == 3)
        #expect(LowWarmthScene.cutoffHz == 380)
    }

    @Test func sameSeedSameSound() {
        let a = render(seed: 7, seconds: 20)
        let b = render(seed: 7, seconds: 20)
        let c = render(seed: 8, seconds: 20)
        #expect(a == b)
        #expect(a != c)
        #expect(rms(a[...]) > 0)
    }

    /// 47 s is inside the fourth chord's swell in (45…48 s), so the seek lands mid-overlap.
    @Test func seekIsExact() {
        let whole = render(seed: 7, seconds: 70)
        let seeked = render(seed: 7, from: 47, seconds: 23)
        let slice = Array(whole[Int(47 * sr)..<Int(70 * sr)])
        #expect(seeked.count == slice.count)
        #expect(seeked == slice)
    }

    /// Added: a seek far into a slow night, rendered in uneven chunks. The seek point is chosen
    /// three cells into a chord that holds for at least four, so the chord sounding there was born
    /// well before the cell before the seek, and only the walk back to its birth finds it.
    @Test func seekIsExactLateSlowAndChunked() throws {
        let warp = WarpDepth(slowness: 1, proportion: 1)
        let spans = LowWarmthScene.chordSpans(seed: 3, warp: .constant(warp), from: 10_000, to: 12_000)
        let long = try #require(spans.first { $0.end - $0.start - 6 >= 4 * LowWarmthScene.cellSeconds })
        let at = long.start + LowWarmthScene.swellSeconds + 3 * LowWarmthScene.cellSeconds + 5
        // The reference starts before that chord's birth, so it cannot share a lookback defect.
        let from = (long.start / LowWarmthScene.cellSeconds).rounded(.down) * LowWarmthScene.cellSeconds - 12
        let lead = Int(((at - from) * sr).rounded())
        let whole = render(seed: 3, warp: warp, from: from, seconds: at - from + 23)
        var scene = LowWarmthScene(seed: 3, sampleRate: sr, warp: .constant(warp), startSecond: at)
        var parts: [Float] = []
        for chunk in [1, 333, 4096, 100_000, Int(23 * sr) - 104_430] {
            var buf = [Float](repeating: 0, count: chunk)
            scene.render(into: &buf, count: chunk)
            parts += buf
        }
        let slice = Array(whole[lead..<(lead + Int(23 * sr))])
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
        #expect(abs(late - early) < 6, "early \(early) dB, late \(late) dB")
        #expect(latePeak <= 1)
    }

    /// Review Focus 4: the lowpass is in Hz, so the spectrum is the same at 48 kHz.
    @Test func staysLow() {
        var centroids: [Double] = []
        for rate in [44100.0, 48000.0] {
            let x = render(seed: 7, seconds: 120, sr: rate)
            let above = Analysis.bandEnergyRatio(x, sampleRate: rate, above: 500)
            let c = Analysis.centroidHz(x, sampleRate: rate)
            print("WARMTH \(rate): \(above * 100)% above 500 Hz, centroid \(c) Hz")
            #expect(above < 0.05, "\(rate) Hz: \(above * 100)% above 500 Hz")
            centroids.append(c)
        }
        #expect(abs(centroids[1] / centroids[0] - 1) <= 0.1, "centroids \(centroids)")
    }

    /// The summed envelope never moves faster than one raised-cosine swell at its steepest.
    @Test func swellIsSmooth() {
        let bound = Double.pi / (2 * LowWarmthScene.swellSeconds * sr) * 1.01
        for warp in [WarpDepth.plain, WarpDepth(slowness: 1)] {
            let spans = LowWarmthScene.chordSpans(seed: 2, warp: .constant(warp), from: 0, to: 300)
            func summed(_ t: Double) -> Double { spans.map { LowWarmthScene.envelope($0, at: t) }.reduce(0, +) }
            var worst = 0.0
            var prev = summed(0)
            for n in 1..<Int(300 * sr) {
                let e = summed(Double(n) / sr)
                worst = max(worst, abs(e - prev))
                prev = e
            }
            #expect(worst <= bound, "slowness \(warp.slowness): step \(worst) over \(bound)")
            #expect(worst > 0.5 * bound, "slowness \(warp.slowness): no swell found (\(worst))")
        }
    }

    /// Over 1200 s, at every frame, one or two chords sound: never a gap, never three.
    @Test func neverSilentNeverStacked() {
        for seed in UInt64(1)...2 {
            for warp in [WarpDepth.plain, WarpDepth(slowness: 1)] {
                let spans = LowWarmthScene.chordSpans(seed: seed, warp: .constant(warp), from: 0, to: 1200)
                var lo = 0, fewest = Int.max, most = 0
                for n in 0..<Int(1200 * sr) {
                    let t = Double(n) / sr
                    while lo < spans.count && spans[lo].end <= t { lo += 1 }
                    var count = 0
                    var i = lo
                    while i < spans.count && spans[i].start < t {
                        if spans[i].end > t { count += 1 }
                        i += 1
                    }
                    fewest = min(fewest, count); most = max(most, count)
                }
                #expect(fewest >= 1, "seed \(seed) slowness \(warp.slowness): a gap")
                #expect(most <= 2, "seed \(seed) slowness \(warp.slowness): \(most) chords at once")
            }
        }
    }

    /// Life is birth to the next chord's birth, in seconds.
    @Test func slownessLengthensChords() {
        func meanLife(_ warp: WarpDepth) -> Double {
            var lives: [Double] = []
            for seed in UInt64(1)...5 {
                let spans = LowWarmthScene.chordSpans(seed: seed, warp: .constant(warp), from: 0, to: 3600)
                for s in spans where s.end <= 3600 {
                    lives.append(s.end - s.start - 2 * LowWarmthScene.swellSeconds)
                }
            }
            return lives.reduce(0, +) / Double(lives.count)
        }
        let plain = meanLife(.plain), slow = meanLife(WarpDepth(slowness: 1))
        #expect(plain == LowWarmthScene.cellSeconds)
        #expect(slow >= 1.6 * plain, "mean life \(slow) s at slowness 1 vs \(plain) s at 0")
    }

    @Test func chordsAreDiatonic() {
        for seed in UInt64(1)...8 {
            let root = LowWarmthScene.rootMIDI(seed: seed)
            #expect((29...36).contains(root))
            // Root position, voiced root, fifth, third an octave up: I, vi, IV, V.
            let triads: [[Int]] = [(0, 4), (9, 3), (5, 4), (7, 4)].map { d, third in
                [root + d, root + d + 7, root + d + third + 12]
            }
            var seen = Set<Int>()
            for cell in 0..<500 {
                let c = LowWarmthScene.chord(seed: seed, cell: cell, warp: .plain)
                let match = triads.firstIndex { t in zip(t, c).allSatisfy { abs(hz(midi: $0) / $1 - 1) < 1e-12 } }
                #expect(match != nil, "seed \(seed) cell \(cell): \(c)")
                if let m = match { seen.insert(m) }
            }
            #expect(seen.count == 4, "seed \(seed): only \(seen.sorted())")
        }
    }

    @Test func proportionIsLevelNeutral() {
        let even = Analysis.rmsDB(render(seed: 4, warp: .plain, seconds: 600)[...])
        let full = Analysis.rmsDB(render(seed: 4, warp: WarpDepth(proportion: 1), seconds: 600)[...])
        print("WARMTH proportion 0: \(even) dB, proportion 1: \(full) dB")
        #expect(abs(full - even) <= 1, "proportion 0: \(even) dB, proportion 1: \(full) dB")
    }

    @Test func peakIsBounded() {
        let bound = LowWarmthScene.peakBound()
        #expect(bound <= 0.9, "peak bound \(bound)")
        let x = render(seed: 11, warp: WarpDepth(proportion: 1), seconds: 600)
        let peak = Double(x.map { abs($0) }.max()!)
        print("WARMTH peak bound \(bound), 600 s peak at proportion 1: \(peak)")
        #expect(peak <= bound, "peak \(peak) over bound \(bound)")
    }

    // MARK: - Listening

    @Test func listeningSample() {
        guard ProcessInfo.processInfo.environment["NIGHT_LISTEN_DIR"] != nil else { return }
        let x = render(seed: 7, seconds: 60)
        writeIfListening(x, name: "warmth-plain", sr: sr)
        print("LISTEN warmth-plain: rms \(Analysis.rmsDB(x[...])) dB, peak \(Analysis.peakDB(x)) dB, centroid \(Analysis.centroidHz(x, sampleRate: sr)) Hz")
    }
}
