import Testing
import Foundation
@testable import NightDSP
import NightPlan

private func channel(_ s: ChannelSettings = .early, sr: Double = 44100, seed: UInt64 = 7, from: Double = 0) -> AMChannel {
    AMChannel(sampleRate: sr, seed: seed, settings: .constant(s), startSecond: from)
}

private func through(_ input: [Float], _ s: ChannelSettings = .early, sr: Double = 44100, seed: UInt64 = 7) -> [Float] {
    var x = input
    var c = channel(s, sr: sr, seed: seed)
    c.process(&x, count: x.count)
    return x
}

private func with(_ edit: (inout ChannelSettings) -> Void) -> ChannelSettings {
    var s = ChannelSettings.early
    edit(&s)
    return s
}

/// RMS in dB of consecutive windows of `seconds`.
private func windowDBs(_ x: [Float], seconds: Double, sr: Double) -> [Double] {
    let n = Int(seconds * sr)
    return stride(from: 0, to: x.count - n + 1, by: n).map { Analysis.rmsDB(x[$0..<($0 + n)]) }
}

@Suite struct AMChannelTests {
    @Test func bandIsNarrow() {
        func measure(_ sr: Double) -> (high: Double, low: Double, centroid: Double) {
            let y = Array(through(noise(seconds: 8, sr: sr, seed: 21), sr: sr)[Int(2 * sr)...])
            return (Analysis.bandEnergyRatio(y, sampleRate: sr, above: 6000),
                    Analysis.bandEnergyRatio(y, sampleRate: sr, below: 120),
                    Analysis.centroidHz(y, sampleRate: sr))
        }
        let a = measure(44100), b = measure(48000)
        for m in [a, b] {
            #expect(m.high < 0.03, "above 6 kHz: \(m.high)")
            #expect(m.low < 0.05, "below 120 Hz: \(m.low)")
        }
        #expect(abs(b.centroid - a.centroid) <= 0.1 * a.centroid, "centroid \(a.centroid) vs \(b.centroid)")
    }

    /// Corners are in Hz at any rate: with the noise, fading and squash off, a quiet sine at either
    /// corner comes out 3 dB below the same sine at 1 kHz (Butterworth: −3 dB at the corner).
    @Test(arguments: [44100.0, 48000.0])
    func cornersAreInHz(sr: Double) {
        let s = with { $0.hissLevelDB = -96; $0.crackleLevelDB = -96; $0.fadeDepth = 0; $0.squash = 0 }
        func level(_ hz: Double) -> Double {
            let y = through(sine(hz, seconds: 3, sr: sr).map { $0 * 0.01 }, s, sr: sr)
            return Analysis.rmsDB(y[Int(1 * sr)...])
        }
        let reference = level(1000)
        for hz in [s.lowCornerHz, s.highCornerHz] {
            let db = level(hz) - reference
            #expect(abs(db + 3.01) <= 0.5, "\(hz) Hz at \(sr): \(db) dB")
        }
    }

    @Test func silenceInHissOut() {
        let sr = 44100.0
        let y = through([Float](repeating: 0, count: Int(60 * sr)), sr: sr)
        let level = Analysis.rmsDB(y[...]), peak = Analysis.peakDB(y)
        #expect(level > -60 && level < -40, "rms \(level) dBFS")
        #expect(peak < -30, "peak \(peak) dBFS")
    }

    @Test func noClicksFromCrackle() {
        let sr = 44100.0
        let y = through([Float](repeating: 0, count: Int(60 * sr)), sr: sr)
        let w = windowDBs(y, seconds: 0.005, sr: sr)
        let median = w.sorted()[w.count / 2]
        let worst = w.max()!
        #expect(worst - median <= 15, "loudest 5 ms window \(worst - median) dB over median")
    }

    /// The crackle grain shape (level offset times Hann) is at most 1 (never above crackleLevelDB),
    /// starts and ends at 0 with no step, and grains arrive at about 40 per second.
    @Test(arguments: [44100.0, 48000.0])
    func crackleGrainsAreSoftAndCapped(sr: Double) {
        let seconds = 30.0
        let n = Int(seconds * sr)
        let g = (0..<n).map { AMChannel.grainShape(seed: 7, frame: $0, sampleRate: sr) }
        var worstStep = 0.0, onsets = 0
        for i in 1..<n {
            worstStep = max(worstStep, abs(g[i] - g[i - 1]))
            if g[i - 1] == 0 && g[i] > 0 { onsets += 1 }
        }
        let limit = Double.pi / (AMChannel.grainMinSeconds * sr) * 1.01   // max slope of a Hann
        #expect(g.max()! <= 1 && g.max()! > 0.5, "grain ceiling \(g.max()!)")
        #expect(worstStep <= limit, "max step \(worstStep) vs \(limit)")
        let rate = Double(onsets) / seconds
        #expect(abs(rate - 40) <= 2, "grains per second \(rate)")
    }

    @Test func fadingMoves() {
        let sr = 44100.0
        let input = sine(1000, seconds: 120, sr: sr).map { $0 * 0.5 }
        func span(_ depth: Double) -> Double {
            let s = with { $0.fadeDepth = depth; $0.fadeRateHz = 0.2 }
            let w = windowDBs(Array(through(input, s, sr: sr)[Int(2 * sr)...]), seconds: 1, sr: sr)
            return w.max()! - w.min()!
        }
        let moving = span(1), still = span(0)
        #expect(moving >= 6, "span at depth 1: \(moving) dB")
        #expect(still < 1, "span at depth 0: \(still) dB")
    }

    /// Selective fading shifts the tone: the sweeping peaking cut moves the 1 s centroid of white
    /// noise, which the broadband fade alone does not.
    @Test func selectiveFadingShiftsTone() {
        let sr = 44100.0
        let input = noise(seconds: 60, sr: sr, seed: 21).map { $0 * 0.3 }
        func span(_ depth: Double) -> Double {
            let y = through(input, with { $0.fadeDepth = depth; $0.fadeRateHz = 0.2 }, sr: sr)
            let n = Int(sr)
            let c = stride(from: 2 * n, to: y.count - n + 1, by: n).map {
                Analysis.centroidHz(Array(y[$0..<($0 + n)]), sampleRate: sr)
            }
            return c.max()! - c.min()!
        }
        let moving = span(1), still = span(0)
        #expect(moving >= 2.5 * still, "centroid span \(moving) Hz at depth 1 vs \(still) Hz at depth 0")
    }

    /// A rate change must not jump the smooth noise: the fade phase only ever advances by rate/sr.
    @Test func fadeRateChangeIsContinuous() {
        let sr = 44100.0
        let jump = Curve<ChannelSettings> { t in
            var s = ChannelSettings.early
            s.fadeRateHz = t >= 10 ? 1 : 0.005
            return s
        }
        var c = AMChannel(sampleRate: sr, seed: 7, settings: jump, startSecond: 0)
        var buf = [Float](repeating: 0, count: 512)
        var last = c.fadePhase, worst = 0.0
        for _ in 0..<Int(20 * sr / 512) {
            c.process(&buf, count: 512)
            let step = c.fadePhase - last
            #expect(step >= 0)
            worst = max(worst, step)
            last = c.fadePhase
        }
        #expect(worst <= 512 / sr * 1.0001, "largest phase step per block \(worst)")
        #expect(last > 5, "the rate rose: phase \(last)")   // ~0.05 + ~8 after the glide
    }

    /// Unity small-signal gain at every squash: a −40 dBFS 1 kHz sine (inside the band, below the
    /// compressor threshold) comes out at its input level. Squash must never be a loudness knob.
    @Test(arguments: [0.0, 0.5, 1.0])
    func warmthHasUnityGainWhenQuiet(squash: Double) {
        let sr = 44100.0
        let s = with { $0.hissLevelDB = -96; $0.crackleLevelDB = -96; $0.fadeDepth = 0; $0.squash = squash }
        let input = sine(1000, seconds: 4, sr: sr).map { $0 * 0.01 }
        let y = through(input, s, sr: sr)
        let db = Analysis.rmsDB(y[Int(1 * sr)...]) - Analysis.rmsDB(input[Int(1 * sr)...])
        #expect(abs(db) <= 0.5, "squash \(squash): \(db) dB")
    }

    /// The crackle ceiling holds end to end: with only crackle (hiss off, no fade), no output sample
    /// is above crackleLevelDB + 1 dB, at any squash.
    @Test(arguments: [0.0, 0.5, 1.0])
    func crackleCapHoldsThroughTheChain(squash: Double) {
        let sr = 44100.0
        let s = with { $0.hissLevelDB = -96; $0.crackleLevelDB = -30; $0.fadeDepth = 0; $0.squash = squash }
        let y = through([Float](repeating: 0, count: Int(60 * sr)), s, sr: sr)
        let peak = Analysis.peakDB(y)
        #expect(peak <= s.crackleLevelDB + 1, "squash \(squash): peak \(peak) dBFS")
    }

    @Test func squashWarmsWithoutClipping() {
        let sr = 44100.0
        let y = through(sine(1000, seconds: 10, sr: sr), with { $0.squash = 1 }, sr: sr)
        #expect(y.allSatisfy { $0.isFinite })
        let peak = y.reduce(Float(0)) { max($0, abs($1)) }
        #expect(peak <= 1.0, "peak \(peak)")
    }

    @Test func seekIsClose() {
        let sr = 44100.0
        let input = noise(seconds: 45, sr: sr, seed: 5).map { $0 * 0.3 }
        let whole = through(input, sr: sr)
        let seeked = seekLeadIn({ channel(sr: sr, from: $0) }, input: input, from: 30, seconds: 10, sr: sr)
        let a = Int(30 * sr)
        let reference = Array(whole[a..<(a + seeked.count)])
        let diff = zip(reference, seeked).map { $0 - $1 }
        let below = Analysis.rmsDB(reference[...]) - Analysis.rmsDB(diff[...])
        #expect(below >= 40, "difference \(below) dB below the signal")
    }

    @Test func chunkedMatchesWhole() {
        let sr = 44100.0
        let moving = Curve<ChannelSettings> { t in
            var s = ChannelSettings.early
            s.highCornerHz = 4500 - 600 * min(t, 4)
            s.fadeDepth = min(t / 4, 1)
            s.fadeRateHz = 0.05 + 0.2 * min(t / 4, 1)
            s.squash = 1 - min(t / 4, 1)
            return s
        }
        let input = noise(seconds: 5, sr: sr, seed: 3).map { $0 * 0.4 }
        var whole = input
        var a = AMChannel(sampleRate: sr, seed: 5, settings: moving, startSecond: 0)
        a.process(&whole, count: whole.count)
        var chunked = input
        var b = AMChannel(sampleRate: sr, seed: 5, settings: moving, startSecond: 0)
        var pos = 0
        for size in [1, 100, 511, 513, 4097, 77, 1103] {
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

    @Test func listeningSample() {
        let sr = 44100.0
        var scene = ChimesScene(seed: 7, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
        var x = [Float](repeating: 0, count: Int(60 * sr))
        scene.render(into: &x, count: x.count)
        var c = channel(sr: sr)
        c.process(&x, count: x.count)
        writeIfListening(x, name: "chimes-am", sr: sr)
        #expect(x.allSatisfy { $0.isFinite })
    }
}
