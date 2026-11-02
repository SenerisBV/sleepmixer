import Testing
import Foundation
@testable import NightDSP
import NightPlan

private func constant(distance: Double = 0, fragmentation: Double = 0) -> Curve<WarpDepth> {
    .constant(WarpDepth(distance: distance, fragmentation: fragmentation))
}

private func gains(_ f: Fragmenter, from: Int, count: Int) -> [Double] {
    (from..<(from + count)).map { f.gain(atFrame: $0) }
}

@Suite struct WarpTests {
    @Test func distanceZeroIsNearlyTransparent() {
        let sr = 44100.0
        let input = sine(500, seconds: 4, sr: sr)
        var out = input
        var d = Distance(sampleRate: sr, seed: 1, warp: constant(), startSecond: 0)
        d.process(&out, count: out.count)
        let a = 2 * Int(sr), b = input.count
        let db = 20 * log10(rms(out[a..<b]) / rms(input[a..<b]))
        #expect(abs(db) < 2, "level change \(db) dB")
    }

    @Test(arguments: [44100.0, 48000.0])
    func distanceDarkens(sr: Double) {
        let n = noise(seconds: 6, sr: sr, seed: 9)
        func centroid(_ depth: Double) -> Double {
            var x = n
            var lp = Biquad.lowpass(cutoff: 3000, sampleRate: sr)   // pink-ish: tilted white noise
            for i in x.indices { x[i] = lp.process(x[i]) }
            var d = Distance(sampleRate: sr, seed: 1, warp: constant(distance: depth), startSecond: 0)
            d.process(&x, count: x.count)
            return Analysis.centroidHz(Array(x[Int(2 * sr)...]), sampleRate: sr)
        }
        let c0 = centroid(0), c1 = centroid(1)
        #expect(c1 <= 0.4 * c0, "centroid \(c0) -> \(c1) Hz")
    }

    @Test(arguments: [44100.0, 48000.0])
    func distanceDarkensTheRoomToo(sr: Double) {
        let n = noise(seconds: 6, sr: sr, seed: 9)
        func highEnergy(_ depth: Double) -> Double {
            var x = n
            var d = Distance(sampleRate: sr, seed: 1, warp: constant(distance: depth), startSecond: 0)
            d.process(&x, count: x.count)
            let y = Array(x[Int(2 * sr)...])
            let total = y.reduce(0.0) { $0 + Double($1) * Double($1) }
            return total * Analysis.bandEnergyRatio(y, sampleRate: sr, above: 2000)
        }
        let drop = 10 * log10(highEnergy(0) / highEnergy(1))
        print("distanceDarkensTheRoomToo \(sr): >2 kHz energy drop \(drop) dB")
        #expect(drop >= 20, "drop \(drop) dB")
    }

    @Test func distanceGlides() {
        let sr = 44100.0
        let jump = Curve<WarpDepth> { t in WarpDepth(distance: t >= 10 ? 1 : 0) }
        let d = Distance(sampleRate: sr, seed: 1, warp: jump, startSecond: 0)
        #expect(d.cornerHz(at: 9.9) > 7900)
        #expect(d.cornerHz(at: 10.1) > 4000)
        #expect(d.cornerHz(at: 16) < 800)
    }

    @Test func distanceChunkedMatchesWhole() {
        let sr = 44100.0
        let warp = Curve<WarpDepth> { t in WarpDepth(distance: min(t / 3, 1)) }
        let input = noise(seconds: 4, sr: sr, seed: 3)
        var whole = input
        var a = Distance(sampleRate: sr, seed: 5, warp: warp, startSecond: 0)
        a.process(&whole, count: whole.count)
        var chunked = input
        var b = Distance(sampleRate: sr, seed: 5, warp: warp, startSecond: 0)
        var pos = 0
        for size in [1, 100, 511, 513, 4097, 77] {
            var piece = Array(chunked[pos..<(pos + size)])
            b.process(&piece, count: size)
            chunked.replaceSubrange(pos..<(pos + size), with: piece)
            pos += size
        }
        var rest = Array(chunked[pos...])
        b.process(&rest, count: rest.count)
        chunked.replaceSubrange(pos..., with: rest)
        #expect(whole == chunked)
    }

    @Test func fragmentationZeroIsUnity() {
        let f = Fragmenter(sampleRate: 44100, seed: 4, warp: constant(), startSecond: 0)
        let g = gains(f, from: 0, count: 120 * 44100)
        #expect(g.allSatisfy { $0 == 1 })
    }

    @Test func fragmentationOneLeavesAboutThirtyPercent() {
        let f = Fragmenter(sampleRate: 44100, seed: 4, warp: constant(fragmentation: 1), startSecond: 0)
        let cells = 1200   // 3600 s
        let present = (0..<cells).filter { f.present(cell: $0) == 1 }.count
        let frac = Double(present) / Double(cells)
        #expect(abs(frac - 0.30) <= 0.05, "present fraction \(frac)")
    }

    @Test func fragmentGainIsSmooth() {
        let sr = 44100.0
        let f = Fragmenter(sampleRate: sr, seed: 4, warp: constant(fragmentation: 1), startSecond: 0)
        let g = gains(f, from: 0, count: Int(600 * sr))
        var worst = 0.0, lo = 1.0, hi = 0.0
        for i in 1..<g.count { worst = max(worst, abs(g[i] - g[i - 1])) }
        for v in g { lo = min(lo, v); hi = max(hi, v) }
        let limit = Double.pi / (2 * Fragmenter.fadeSeconds * sr) * 1.01
        #expect(worst <= limit, "max step \(worst) vs \(limit)")
        #expect(lo == 0 && hi == 1, "gain range \(lo)...\(hi)")   // fades really happen
    }

    @Test func fragmentSeekIsExact() {
        let sr = 44100.0
        let warp = constant(fragmentation: 1)
        let continuous = Fragmenter(sampleRate: sr, seed: 4, warp: warp, startSecond: 0)
        var seeked = Fragmenter(sampleRate: sr, seed: 4, warp: warp, startSecond: 100)
        let n = Int(60 * sr)
        var ones = [Float](repeating: 1, count: n)
        seeked.process(&ones, count: n)
        let expected = gains(continuous, from: Int(100 * sr), count: n).map { Float($0) }
        #expect(ones == expected)
        #expect(ones.contains { $0 < 0.5 } && ones.contains { $0 > 0.5 })
    }

    @Test func fragmenterChunkedMatchesWhole() {
        let sr = 44100.0
        let warp = constant(fragmentation: 1)
        let input = noise(seconds: 20, sr: sr, seed: 8)
        var whole = input
        var a = Fragmenter(sampleRate: sr, seed: 11, warp: warp, startSecond: 0)
        a.process(&whole, count: whole.count)
        var b = Fragmenter(sampleRate: sr, seed: 11, warp: warp, startSecond: 0)
        var chunked = input
        var pos = 0
        for size in [1, 999, 44100, 12345, 7] {
            var piece = Array(chunked[pos..<(pos + size)])
            b.process(&piece, count: size)
            chunked.replaceSubrange(pos..<(pos + size), with: piece)
            pos += size
        }
        var rest = Array(chunked[pos...])
        b.process(&rest, count: rest.count)
        chunked.replaceSubrange(pos..., with: rest)
        #expect(whole == chunked)
        #expect(whole.contains { $0 == 0 } && !zip(whole, input).allSatisfy { $0 == $1 })
    }
}
