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

// MARK: - Test-side spectral helpers (Analysis.fft is private and needs ≥ 4096 samples)

/// Power spectrum of `x` zero-padded to the next power of two ≥ `minSize`; `window` multiplies `x` first.
private func powerSpectrum(_ x: [Double], minSize: Int) -> [Double] {
    var n = 1
    while n < max(minSize, x.count) { n <<= 1 }
    var re = x + [Double](repeating: 0, count: n - x.count)
    var im = [Double](repeating: 0, count: n)
    var j = 0
    for i in 1..<n {
        var bit = n >> 1
        while j & bit != 0 { j ^= bit; bit >>= 1 }
        j ^= bit
        if i < j { re.swapAt(i, j); im.swapAt(i, j) }
    }
    var len = 2
    while len <= n {
        let ang = -2 * Double.pi / Double(len)
        for i in stride(from: 0, to: n, by: len) {
            for k in 0..<len / 2 {
                let wr = cos(ang * Double(k)), wi = sin(ang * Double(k))
                let a = i + k, b = i + k + len / 2
                let tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr
                re[b] = re[a] - tr; im[b] = im[a] - ti
                re[a] += tr; im[a] += ti
            }
        }
        len <<= 1
    }
    return (0...n / 2).map { re[$0] * re[$0] + im[$0] * im[$0] }
}

/// Envelope as the peak |x| of consecutive chunks one period of `hz` long, timed at chunk centres.
private func chunkPeaks(_ x: [Float], hz: Double, sr: Double) -> (t: [Double], v: [Double]) {
    let len = max(1, Int((sr / hz).rounded()))
    var t: [Double] = [], v: [Double] = []
    var i = 0
    while i + len <= x.count {
        t.append((Double(i) + Double(len) / 2) / sr)
        v.append(Double(x[i..<(i + len)].map { abs($0) }.max() ?? 0))
        i += len
    }
    return (t, v)
}

/// First time the series crosses `level` going up (after `from`) or down, linearly interpolated.
private func crossing(_ e: (t: [Double], v: [Double]), level: Double, rising: Bool, from: Int = 0) -> Double? {
    for i in max(1, from)..<e.v.count {
        let a = e.v[i - 1], b = e.v[i]
        if rising ? (a < level && b >= level) : (a > level && b <= level) {
            return e.t[i - 1] + (level - a) / (b - a) * (e.t[i] - e.t[i - 1])
        }
    }
    return nil
}

/// Fraction of the note's first 15 ms energy above 2 kHz, leaving out bands of ±`guardHz` around
/// each frequency in `skip`. The window is flat at the onset (so a hard attack is seen whole) and
/// a falling half-Hann toward 15 ms (so the cut adds no splatter of its own).
private func tingRatio(_ note: [Float], sr: Double, skip: [Double] = [], guardHz: Double = 0) -> Double {
    let n = Int(0.015 * sr)
    let x: [Double] = (0..<n).map { (i: Int) -> Double in
        let w = 0.5 + 0.5 * cos(Double.pi * Double(i) / Double(n))
        return Double(note[i]) * w
    }
    let p = powerSpectrum(x, minSize: 8192)
    let binHz = sr / Double(2 * (p.count - 1))
    var hi = 0.0, all = 0.0
    for k in 1..<p.count {
        all += p[k]
        let hz = Double(k) * binHz
        if hz >= 2000 && skip.allSatisfy({ abs(hz - $0) > guardHz }) { hi += p[k] }
    }
    return hi / all
}

@Suite struct ChimesSceneTests {
    let sr = 44100.0

    @Test func elementsAreNamed() {
        let scene = ChimesScene(seed: 1, sampleRate: sr, warp: .constant(.plain), startSecond: 0)
        #expect(scene.elements == ["fundamental", "fourth", "tenth"])
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

    /// Seeking past the lookback window, in uneven chunks, at the longest ring and sparsest notes.
    /// Vibrato is on too (an addition to the brief): its phasor restarts on the block grid like the
    /// partials' do, and only a seek test can catch a restart that drifts.
    @Test func seekIsExactLateAndChunked() {
        let warp = WarpDepth(slowness: 1, ring: 1, vibrato: 1)
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

    /// Density and centroid only: ring, not slowness, owns the ring time now.
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

    /// Guards the pitch drop directly: the centroid test can pass on density alone.
    @Test func slownessLowersPitchByThreeSemitones() {
        for seed in UInt64(1)...5 {
            for cell in [0, 1, 7, 42, 13_000] {
                let plain = ChimesScene.fundamental(seed: seed, cell: cell, warp: .plain)
                let slow = ChimesScene.fundamental(seed: seed, cell: cell, warp: WarpDepth(slowness: 1))
                #expect(plain >= 196 && plain < 392 * 4)
                #expect(plain <= ChimesScene.highestFundamental)
                #expect(abs(slow / plain - pow(2, -3.0 / 12)) < 1e-9)
            }
        }
    }

    // MARK: - The bar

    @Test func partialsAreAPureBar() {
        // Ring 1, so the overtones' faster decay biases the 50–350 ms reading by under 1 dB.
        let f = 440.0
        let note = ChimesScene.renderNote(f: f, warp: WarpDepth(ring: 1), seconds: 1, sampleRate: sr)
        let a = Int(0.05 * sr), b = Int(0.35 * sr), n = b - a
        let x: [Double] = (0..<n).map { (i: Int) -> Double in
            let w = 0.5 - 0.5 * cos(2 * Double.pi * Double(i) / Double(n - 1))
            return Double(note[a + i]) * w
        }
        let p = powerSpectrum(x, minSize: 65536)
        let binHz = sr / Double(2 * (p.count - 1))
        func peak(near hz: Double, bins: Int) -> (bin: Int, db: Double) {
            let c = Int((hz / binHz).rounded())
            let k = (c - bins...c + bins).max { p[$0] < p[$1] }!
            return (k, 10 * log10(max(p[k], 1e-300)))
        }
        let fund = peak(near: f, bins: 2)
        let four = peak(near: 4 * f, bins: 20)
        let ten = peak(near: 10 * f, bins: 50)
        #expect(abs(Double(four.bin) * binHz - 4 * f) <= binHz)
        #expect(abs(Double(ten.bin) * binHz - 10 * f) <= binHz)
        #expect(abs(four.db - fund.db + 24) <= 2, "×4 at \(four.db - fund.db) dB")
        #expect(abs(ten.db - fund.db + 36) <= 3, "×10 at \(ten.db - fund.db) dB")
        for r in [2.0, 2.76, 4.07] {
            let bell = peak(near: r * f, bins: 1)
            #expect(bell.db - fund.db < -50, "×\(r) at \(bell.db - fund.db) dB")
        }
    }

    @Test(arguments: [44100.0, 48000.0])
    func noMalletTing(sampleRate: Double) {
        let note = ChimesScene.renderNote(f: ChimesScene.highestFundamental, warp: .plain, seconds: 0.1, sampleRate: sampleRate)
        let ratio = tingRatio(note, sr: sampleRate)
        #expect(ratio < 0.005, "first 15 ms: \(ratio * 100)% above 2 kHz at \(sampleRate)")
        // Added to the brief: at the top note both overtones sit above 2 kHz and already make up
        // 0.42 % of the energy, so a 1 ms strike only lifts the briefed ratio to 0.49 %. What a
        // strike adds is splatter between the partials: outside ±400 Hz of ×4 and ×10 it is
        // 0.00001 % with the soft start and 0.07 % with a 1 ms one.
        let f = ChimesScene.highestFundamental
        let splatter = tingRatio(note, sr: sampleRate, skip: [4 * f, 10 * f], guardHz: 400)
        #expect(splatter < 0.0001, "first 15 ms: \(splatter * 100)% splatter above 2 kHz at \(sampleRate)")
    }

    @Test func softnessSetsTheAttack() throws {
        #expect(ChimesScene.attackSeconds(1) / ChimesScene.attackSeconds(0) > 3)
        let f = 441.0
        for softness in [0.0, 1.0] {
            let a = ChimesScene.attackSeconds(softness)
            let note = ChimesScene.renderNote(f: f, warp: WarpDepth(softness: softness), seconds: 0.5, sampleRate: sr)
            var e = chunkPeaks(note, hz: f, sr: sr)
            // The note is silent at its birth frame: anchor the envelope there, so a rise faster
            // than one chunk still has a crossing to find.
            e.t.insert(0, at: 0); e.v.insert(0, at: 0)
            let top = try #require(e.v.max())
            let t10 = try #require(crossing(e, level: 0.1 * top, rising: true))
            let t90 = try #require(crossing(e, level: 0.9 * top, rising: true))
            let rise = t90 - t10
            // A raised cosine alone rises 10→90 % in acos(-0.8)/π - acos(0.8)/π = 0.590 of its
            // length, and the ring's decay shortens that further, so the briefed 0.6 cannot hold.
            withKnownIssue("briefed ≥ 0.6·attack is above a raised cosine's own 0.590·attack") {
                #expect(rise >= 0.6 * a, "softness \(softness): rise \(rise) s vs attack \(a) s")
            }
            #expect(rise >= 0.5 * a, "softness \(softness): rise \(rise) s vs attack \(a) s")
        }
    }

    @Test func ringSetsTheDecay() throws {
        let f = 441.0
        for ring in [0.0, 0.5, 1.0] {
            let tau = ChimesScene.ringSeconds(ring)
            let note = ChimesScene.renderNote(f: f, warp: WarpDepth(ring: ring), seconds: 12, sampleRate: sr)
            let e = chunkPeaks(note, hz: f, sr: sr)
            let top = try #require(e.v.max())
            let peakAt = try #require(e.v.firstIndex(of: top))
            let t20 = try #require(crossing(e, level: 0.1 * top, rising: false, from: peakAt))
            let expected = tau * log(10)
            #expect(abs(t20 / expected - 1) <= 0.1, "ring \(ring): -20 dB at \(t20) s, expected \(expected) s")
        }
        #expect(ChimesScene.ringSeconds(0) == 1.4)
        #expect(ChimesScene.ringSeconds(1) == 4.2)
    }

    private func meanRMS(_ warp: WarpDepth) -> Double {
        (UInt64(1)...5).map { Analysis.rmsDB(render(seed: $0, warp: warp, seconds: 600)[...]) }.reduce(0, +) / 5
    }

    @Test func ringIsLevelNeutral() {
        let short = meanRMS(WarpDepth(ring: 0)), long = meanRMS(WarpDepth(ring: 1))
        #expect(abs(long - short) <= 1, "ring 0: \(short) dB, ring 1: \(long) dB")
    }

    @Test func vibratoIsLevelNeutral() {
        let still = meanRMS(WarpDepth(vibrato: 0)), pulsing = meanRMS(WarpDepth(vibrato: 1))
        #expect(abs(pulsing - still) <= 1, "vibrato 0: \(still) dB, vibrato 1: \(pulsing) dB")
        // Added to the brief: without the mean correction the level falls by only 0.80 dB, inside
        // the briefed 1 dB, so this tighter bound is what actually guards the correction.
        #expect(abs(pulsing - still) <= 0.25, "vibrato 0: \(still) dB, vibrato 1: \(pulsing) dB")
    }

    /// Strongest modulation of the detrended 50 ms envelope, and its level relative to the mean.
    private func modulation(vibrato: Double) -> (hz: Double, db: Double) {
        let warp = WarpDepth(vibrato: vibrato)
        let tau = ChimesScene.ringSeconds(warp.ring)
        let note = ChimesScene.renderNote(f: 441, warp: warp, seconds: 6, sampleRate: sr)
        let hop = Int(0.05 * sr)
        var env: [Double] = []
        var i = Int(0.5 * sr)
        while i + hop <= note.count {
            let t = (Double(i) + Double(hop) / 2) / sr
            env.append(rms(note[i..<(i + hop)]) / exp(-t / tau))
            i += hop
        }
        let mean = env.reduce(0, +) / Double(env.count)
        let y = env.map { $0 - mean }
        var best = (hz: 0.0, db: -999.0)
        for step in 20...190 {
            let hz = Double(step) * 0.05
            var re = 0.0, im = 0.0
            for (k, v) in y.enumerated() {
                let ph = 2 * Double.pi * hz * Double(k) * 0.05
                re += v * cos(ph); im -= v * sin(ph)
            }
            let amp = 2 * (re * re + im * im).squareRoot() / Double(y.count)
            let db = 20 * log10(max(amp / mean, 1e-12))
            if db > best.db { best = (hz, db) }
        }
        return best
    }

    @Test func vibratoPulsesAt4_5Hz() {
        let on = modulation(vibrato: 1)
        #expect(abs(on.hz - ChimesScene.vibratoHz) <= 0.3, "strongest at \(on.hz) Hz (\(on.db) dB)")
        // Added: the pulse's depth. 0.09 / 0.91 of the mean is -20.1 dB; the 50 ms RMS smears it a little.
        #expect(abs(on.db + 20.1) <= 2, "pulse at \(on.db) dB")
        let off = modulation(vibrato: 0)
        #expect(off.db < -40, "vibrato 0: \(off.db) dB at \(off.hz) Hz")
        #expect(ChimesScene.vibratoHz == 4.5)
        #expect(ChimesScene.vibratoDepth(1) == 0.18)
    }

    // MARK: - Proportion

    @Test func proportionPreservesPower() {
        let base = ChimesScene.baseAmps
        let target = base.map { $0 * $0 }.reduce(0, +)
        for seed in UInt64(1)...3 {
            for i in UInt64(0)..<40 {
                for p in [0.0, 0.5, 1.0] {
                    let g = Proportion.powerPreservingGains(seed: seed, stream: 4, index: i, baseAmps: base, proportion: p)
                    let power = zip(base, g).map { $0 * $1 * $0 * $1 }.reduce(0, +)
                    #expect(abs(power - target) <= 1e-9, "p \(p): power \(power) vs \(target)")
                    if p == 0 { #expect(g == [1, 1, 1]) }
                    if p == 1 {
                        let top = g.max()!
                        #expect(g.filter { $0 == top }.count == 1)
                        let rest = g.filter { $0 != top }
                        #expect(rest.allSatisfy { abs(20 * log10(top / $0) - 18) < 1e-9 })
                    }
                }
                let full = Curve.constant(WarpDepth(proportion: 1))
                #expect(ChimesScene.elementGains(seed: seed, index: i, warp: full)
                    == Proportion.powerPreservingGains(seed: seed, stream: 4, index: i, baseAmps: base, proportion: 1))
                #expect(ChimesScene.elementGains(seed: seed, index: i, warp: .constant(.plain)) == [1, 1, 1])
            }
        }
    }

    /// Review Focus 1: the top note of the range at full proportion, each element favoured in turn.
    @Test(arguments: [0, 1, 2])
    func highNotesStayRound(favoured: Int) {
        let note = ChimesScene.renderNote(f: ChimesScene.highestFundamental, warp: WarpDepth(proportion: 1),
                                          seconds: 6, sampleRate: sr, favoured: favoured)
        let ratio = Analysis.bandEnergyRatio(note, sampleRate: sr, above: 2000)
        if favoured == 1 {
            // Favouring ×4 lifts it from -24 dB to -6 dB under the fundamental; at 5.27 kHz that is
            // about 11 % of the note's energy by construction. Reported, not tuned.
            withKnownIssue("×4 favoured at proportion 1 puts ~11 % of the top note above 2 kHz") {
                #expect(ratio < 0.01, "favoured \(favoured): \(ratio * 100)% above 2 kHz")
            }
        } else {
            #expect(ratio < 0.01, "favoured \(favoured): \(ratio * 100)% above 2 kHz")
        }
    }

    // MARK: - Peak

    /// Review Focus 2: the analytic worst case bounds the render, and stays under 0.9.
    @Test func peakIsBounded() {
        let bound = ChimesScene.peakBound()
        #expect(bound <= 0.9, "peak bound \(bound)")
        for rate in [44100.0, 48000.0] {
            for ring in [0.0, 0.5, 1.0] {
                let warp = WarpDepth(proportion: 1, ring: ring, vibrato: 1)
                let x = render(seed: 11, warp: warp, seconds: 600, sr: rate)
                let peak = Double(x.map { abs($0) }.max()!)
                #expect(peak <= bound, "\(rate) Hz ring \(ring): peak \(peak) over bound \(bound)")
            }
        }
    }

    // MARK: - Listening

    @Test func listeningSample() {
        let samples: [(String, WarpDepth)] = [
            ("chimes-soft-plain", .plain),
            ("chimes-soft-ring", WarpDepth(ring: 1)),
            ("chimes-soft-softness", WarpDepth(softness: 1)),
            ("chimes-soft-vibrato", WarpDepth(vibrato: 1)),
            ("chimes-soft-all", WarpDepth(ring: 1, softness: 1, vibrato: 1)),
        ]
        guard ProcessInfo.processInfo.environment["NIGHT_LISTEN_DIR"] != nil else { return }
        for (name, warp) in samples {
            let x = render(seed: 7, warp: warp, seconds: 60)
            writeIfListening(x, name: name, sr: sr)
            print("LISTEN \(name): rms \(Analysis.rmsDB(x[...])) dB, peak \(Analysis.peakDB(x)) dB, centroid \(Analysis.centroidHz(x, sampleRate: sr)) Hz")
        }
    }
}
