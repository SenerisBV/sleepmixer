import Foundation
import Testing
import NightPlan
@testable import NightDSP

private func rainRender(seed: UInt64, from: Double = 0, seconds: Double, sr: Double = 44100) -> [Float] {
    var rain = RainSound(seed: seed, sampleRate: sr, startSecond: from)
    let n = Int(seconds * sr)
    var out = [Float](repeating: 0, count: n)
    rain.render(into: &out, count: n)
    return out
}

private func render<S: SoundSource>(_ make: () -> S, seconds: Double, sr: Double = 44100) -> [Float] {
    var s = make()
    let n = Int(seconds * sr)
    var out = [Float](repeating: 0, count: n)
    s.render(into: &out, count: n)
    return out
}

private func maxStep(_ x: [Float]) -> Double {
    zip(x.dropFirst(), x).map { abs(Double($0) - Double($1)) }.max()!
}

private func windowLevelsDB(_ x: [Float], window: Int, count: Int) -> [Double] {
    (0..<count).map { 20 * log10(rms(x[($0 * window)..<(($0 + 1) * window)])) }
}

@Suite struct WindowSoundTests {
    let sr = 44100.0

    @Test func rainIsDeterministic() {
        #expect(rainRender(seed: 5, seconds: 10) == rainRender(seed: 5, seconds: 10))
        #expect(rainRender(seed: 5, seconds: 2) != rainRender(seed: 6, seconds: 2))
    }

    @Test func rainPeakIsBounded() {
        for seed in UInt64(0)..<8 {
            let x = rainRender(seed: seed, seconds: 60)
            #expect(x.map { abs($0) }.max()! <= 0.9)
            #expect(rms(x[...]) > 0.01)
        }
    }

    @Test func rainIsSteady() {
        let x = rainRender(seed: 3, seconds: 600)
        let win = Int(30 * sr)
        let levels = (0..<20).map { 20 * log10(rms(x[($0 * win)..<(($0 + 1) * win)])) }
        let median = levels.sorted()[10]
        for l in levels { #expect(abs(l - median) <= 6) }
    }

    @Test func rainIsFelted() {
        let x = rainRender(seed: 3, seconds: 60)
        writeIfListening(x, name: "rain", sr: sr)
        let level = rms(x[...])
        let peak = Double(x.map { abs($0) }.max()!)
        #expect(peak / level <= 6)
        // R1 (controller ruling): the plan's absolute "largest step <= 0.05" is a level, not a
        // softness, test: steps scale with the signal, and at a usable level the lowpassed noise wash
        // alone steps past 0.05 (it did at RMS 0.03). What it guards is "no clicks", so the step is
        // measured against the signal's own typical step: a click is many times the RMS step, while
        // lowpassed Gaussian noise tops out near 6x over a minute. Plus the drops' attack is checked
        // directly, since that is where a hard edge would come from.
        var maxStep = 0.0, stepEnergy = 0.0
        for i in 1..<x.count {
            let d = abs(Double(x[i]) - Double(x[i - 1]))
            maxStep = max(maxStep, d); stepEnergy += d * d
        }
        let rmsStep = (stepEnergy / Double(x.count - 1)).squareRoot()
        #expect(maxStep <= 7 * rmsStep)
        #expect(RainSound.dropLengthRange.lowerBound / 2 >= RainSound.dropAttackMinSeconds)
        #expect(RainSound.dropAttackMinSeconds >= 0.003)
    }

    /// The behavioral felted check: with the wash off, the drops alone must have no hard edges.
    @Test func rainDropsAreSoftOnTheirOwn() {
        for seed in UInt64(0)..<4 {
            var rain = RainSound(seed: seed, sampleRate: sr, startSecond: 0)
            rain.washLevel = 0
            var x = [Float](repeating: 0, count: Int(30 * sr))
            rain.render(into: &x, count: x.count)
            #expect(rms(x[...]) > 0.005)   // the drops really are there
            let step = zip(x.dropFirst(), x).map { abs(Double($0) - Double($1)) }.max()!
            #expect(step <= 0.05)
        }
    }

    @Test func rainSeeksCloseToContinuous() {
        let whole = rainRender(seed: 3, seconds: 130)
        let slice = Array(whole[Int(120 * sr)..<Int(130 * sr)])
        let seeked = seekLeadIn({ RainSound(seed: 3, sampleRate: sr, startSecond: $0) }, from: 120, seconds: 10, sr: sr)
        #expect(seeked.count == slice.count)
        let diff = zip(seeked, slice).map { $0 - $1 }
        #expect(rms(diff[...]) <= rms(slice[...]) * pow(10, -20.0 / 20))
    }

    // MARK: - Stream

    @Test func streamIsDeterministic() {
        let a = render({ StreamSound(seed: 5, sampleRate: 44100, startSecond: 0) }, seconds: 10)
        let b = render({ StreamSound(seed: 5, sampleRate: 44100, startSecond: 0) }, seconds: 10)
        let c = render({ StreamSound(seed: 6, sampleRate: 44100, startSecond: 0) }, seconds: 2)
        #expect(a == b)
        #expect(Array(a[0..<c.count]) != c)
    }

    @Test func streamPeakIsBounded() {
        for seed in UInt64(0)..<8 {
            let x = render({ StreamSound(seed: seed, sampleRate: 44100, startSecond: 0) }, seconds: 60)
            #expect(x.map { abs($0) }.max()! <= 0.9)
            #expect(rms(x[...]) > 0.01)
        }
    }

    @Test func streamIsSteady() {
        let x = render({ StreamSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 600)
        let levels = windowLevelsDB(x, window: Int(30 * sr), count: 20)
        let median = levels.sorted()[10]
        for l in levels { #expect(abs(l - median) <= 6) }
    }

    @Test func streamIsFelted() {
        let x = render({ StreamSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 60)
        writeIfListening(x, name: "stream", sr: sr)
        #expect(maxStep(x) <= 0.05)
        // The bubbles' attacks, without the bed to hide them: the bubbles really are there and
        // their largest step is far under the bound.
        for seed in UInt64(0)..<4 {
            var s = StreamSound(seed: seed, sampleRate: sr, startSecond: 0)
            s.bedLevel = 0
            var b = [Float](repeating: 0, count: Int(30 * sr))
            s.render(into: &b, count: b.count)
            #expect(rms(b[...]) > 0.003)
            // Stricter than the plan's 0.05 (R1): a chirp that starts and stops at zero crosses
            // zero anyway, so only a tight bound catches a missing attack/release window.
            #expect(maxStep(b) <= 0.02)
        }
        #expect(StreamSound.bubbleLengthRange.lowerBound / 2 >= 0.01)   // attack >= 10 ms
    }

    // MARK: - Crickets

    @Test func cricketsAreDeterministic() {
        let a = render({ CricketsSound(seed: 5, sampleRate: 44100, startSecond: 0) }, seconds: 30)
        let b = render({ CricketsSound(seed: 5, sampleRate: 44100, startSecond: 0) }, seconds: 30)
        let c = render({ CricketsSound(seed: 6, sampleRate: 44100, startSecond: 0) }, seconds: 30)
        #expect(a == b)
        #expect(a != c)
        #expect(rms(a[...]) > 0)
    }

    @Test func cricketsPeakIsBounded() {
        for seed in UInt64(0)..<8 {
            let x = render({ CricketsSound(seed: seed, sampleRate: 44100, startSecond: 0) }, seconds: 60)
            #expect(x.map { abs($0) }.max()! <= 0.9)
            #expect(rms(x[...]) > 0.001)
        }
    }

    @Test func cricketsAreSteady() {
        let x = render({ CricketsSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 600)
        let levels = windowLevelsDB(x, window: Int(60 * sr), count: 10)
        let median = levels.sorted()[5]
        for l in levels { #expect(abs(l - median) <= 6) }
    }

    @Test func cricketsAreFelted() {
        let x = render({ CricketsSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 60)
        writeIfListening(x, name: "crickets", sr: sr)
        // R1: the plan's absolute "largest step <= 0.05" is a level test here. Crickets must sit
        // 12 dB under rain, which needs a pulse amplitude near 0.18, and a pure 4.5 kHz sine of that
        // size steps by about 0.1 on its own. What "felted" guards is "no click", so the step is
        // bounded by the carrier's own steepest step at the render's peak (25% allowed for the
        // pixellation). That bound is loose against a click from silence, so the envelope check
        // below is the one that guards the attacks.
        let peak = Double(x.map { abs($0) }.max()!)
        let carrierStep = peak * 2 * Double.pi * CricketsSound.carrierHz * (1 + CricketsSound.carrierJitter) / sr
        #expect(maxStep(x) <= 1.25 * carrierStep)
        // Behavioral: with the carrier replaced by a constant, only the pulse envelopes remain and
        // a hard attack would step by the pulse's whole amplitude.
        for seed in UInt64(0)..<4 {
            var s = CricketsSound(seed: seed, sampleRate: sr, startSecond: 0)
            s.envelopeOnly = true
            var e = [Float](repeating: 0, count: Int(60 * sr))
            s.render(into: &e, count: e.count)
            #expect(e.map { abs($0) }.max()! > 0.03)   // the pulses are really there
            #expect(maxStep(e) <= 0.005)
        }
    }

    @Test func cricketsSitUnderRain() {
        let rain = rainRender(seed: 1, seconds: 120)
        let crickets = render({ CricketsSound(seed: 1, sampleRate: 44100, startSecond: 0) }, seconds: 120)
        let under = 20 * log10(rms(rain[...])) - 20 * log10(rms(crickets[...]))
        #expect(under >= 10 && under <= 14)
    }

    @Test func cricketsPause() {
        let x = render({ CricketsSound(seed: 1, sampleRate: 44100, startSecond: 0) }, seconds: 600)
        let overall = rms(x[...])
        let win = Int(5 * sr), hop = Int(0.1 * sr)
        var quietest = Double.infinity
        var start = 0
        while start + win <= x.count {
            quietest = min(quietest, rms(x[start..<(start + win)]))
            start += hop
        }
        #expect(quietest <= overall * pow(10, -30.0 / 20))
    }

    @Test func cricketsSeekCloseToContinuous() {
        let whole = render({ CricketsSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 130)
        let slice = Array(whole[Int(120 * sr)..<Int(130 * sr)])
        let seeked = seekLeadIn({ CricketsSound(seed: 3, sampleRate: sr, startSecond: $0) }, from: 120, seconds: 10, sr: sr)
        let diff = zip(seeked, slice).map { $0 - $1 }
        #expect(rms(diff[...]) <= rms(slice[...]) * pow(10, -20.0 / 20))
    }

    @Test func streamSeeksCloseToContinuous() {
        let whole = render({ StreamSound(seed: 3, sampleRate: 44100, startSecond: 0) }, seconds: 130)
        let slice = Array(whole[Int(120 * sr)..<Int(130 * sr)])
        let seeked = seekLeadIn({ StreamSound(seed: 3, sampleRate: sr, startSecond: $0) }, from: 120, seconds: 10, sr: sr)
        let diff = zip(seeked, slice).map { $0 - $1 }
        #expect(rms(diff[...]) <= rms(slice[...]) * pow(10, -20.0 / 20))
    }

    // MARK: - Thunder

    private let full = Curve.constant(Sudden(rateScale: 1, gainDB: 0))

    @Test func thunderIsDeterministic() {
        let a = render({ ThunderSound(seed: 2, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 250)
        let b = render({ ThunderSound(seed: 2, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 250)
        let c = render({ ThunderSound(seed: 3, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 250)
        #expect(a == b)
        #expect(a != c)
        #expect(rms(a[...]) > 0)
    }

    @Test func thunderPeakIsBounded() {
        for seed in UInt64(0)..<3 {
            let x = render({ ThunderSound(seed: seed, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 600)
            #expect(x.map { abs($0) }.max()! <= 0.9)
            #expect(rms(x[...]) > 0.0005)
        }
    }

    @Test func thunderIsDistant() {
        let t = ThunderSound(seed: 2, sampleRate: sr, startSecond: 0, sudden: full)
        let x = render({ ThunderSound(seed: 2, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 1800)
        writeIfListening(x, name: "thunder", sr: sr)
        let rolls = (0..<8).compactMap { t.roll(cell: $0) }
        #expect(rolls.count >= 1)
        // Every roll's 10-90% rise, measured on the rendered signal (200 ms RMS envelope).
        let w = Int(0.2 * sr), hop = Int(0.01 * sr)
        for r in rolls {
            var env: [Double] = []
            var s = r.start - Int(0.5 * sr)
            while s + w <= min(x.count, r.start + r.length) { env.append(rms(x[s..<(s + w)])); s += hop }
            let peak = env.max()!
            let t10 = env.firstIndex { $0 >= 0.1 * peak }!
            let t90 = env.firstIndex { $0 >= 0.9 * peak }!
            #expect(Double(t90 - t10) * Double(hop) / sr >= 0.5)
        }
        // Energy above 1 kHz is at least 30 dB under the energy below 600 Hz.
        var lows = [Biquad.lowpass(cutoff: 600, sampleRate: sr), Biquad.lowpass(cutoff: 600, sampleRate: sr)]
        var highs = [Biquad.highpass(cutoff: 1000, sampleRate: sr), Biquad.highpass(cutoff: 1000, sampleRate: sr)]
        var eLow = 0.0, eHigh = 0.0
        for v in x {
            var l = v, h = v
            for k in 0..<2 { l = lows[k].process(l); h = highs[k].process(h) }
            eLow += Double(l * l); eHigh += Double(h * h)
        }
        #expect(10 * log10(eLow / eHigh) >= 30)
        #expect(x.map { abs($0) }.max()! <= 0.5)
    }

    @Test func thunderSilentWhenRateZero() {
        let off = Curve.constant(Sudden(rateScale: 0, gainDB: 0))
        let x = render({ ThunderSound(seed: 2, sampleRate: 44100, startSecond: 0, sudden: off) }, seconds: 1800)
        #expect(x.allSatisfy { $0 == 0 })
    }

    @Test func thunderRecedes() {
        // Over 2 h. The rolls are found from the grid, and only their spans are rendered (seeked
        // from just before each roll), so the test stays quick.
        func run(_ sudden: Curve<Sudden>) -> (rolls: Int, loudest: Float) {
            let t = ThunderSound(seed: 2, sampleRate: sr, startSecond: 0, sudden: sudden)
            let rolls = (0..<Int(7200 / ThunderSound.cellSeconds)).compactMap { t.roll(cell: $0) }
            var loudest: Float = 0
            for r in rolls {
                let from = Double(r.start) / sr - 1
                let x = seekLeadIn({ ThunderSound(seed: 2, sampleRate: sr, startSecond: $0, sudden: sudden) },
                                   from: from, seconds: Double(r.length) / sr + 2, sr: sr)
                loudest = max(loudest, x.map { abs($0) }.max()!)
            }
            return (rolls.count, loudest)
        }
        let loud = run(full)
        let receded = run(Curve.constant(Sudden(rateScale: 0.25, gainDB: -12)))
        #expect(loud.rolls >= 20)
        #expect(receded.rolls < loud.rolls)
        #expect(receded.rolls >= 1)
        #expect(loud.loudest > 0.1)
        #expect(receded.loudest <= loud.loudest * 0.3)   // -12 dB is 0.25 on the same rolls
    }

    @Test func thunderSeeksCloseToContinuous() {
        let whole = render({ ThunderSound(seed: 2, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 400)
        let from = 240.0
        let slice = Array(whole[Int(from * sr)..<Int((from + 60) * sr)])
        let seeked = seekLeadIn({ ThunderSound(seed: 2, sampleRate: sr, startSecond: $0, sudden: full) }, from: from, seconds: 60, sr: sr)
        let diff = zip(seeked, slice).map { $0 - $1 }
        #expect(rms(diff[...]) <= rms(slice[...]) * pow(10, -20.0 / 20))
    }

    // MARK: - Fire

    @Test func fireIsDeterministic() {
        let a = render({ FireSound(seed: 5, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 120)
        let b = render({ FireSound(seed: 5, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 120)
        let c = render({ FireSound(seed: 6, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 120)
        #expect(a == b)
        #expect(a != c)
        #expect(rms(a[...]) > 0)
    }

    @Test func firePeakIsBounded() {
        for seed in UInt64(0)..<4 {
            let x = render({ FireSound(seed: seed, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 300)
            #expect(x.map { abs($0) }.max()! <= 0.9)
            #expect(rms(x[...]) > 0.001)
        }
    }

    @Test func fireCracklesSteadilyWhenPopsAreGone() {
        let off = Curve.constant(Sudden(rateScale: 0, gainDB: 0))
        let x = render({ FireSound(seed: 3, sampleRate: 44100, startSecond: 0, sudden: off) }, seconds: 600)
        #expect(rms(x[...]) > 0.001)
        let levels = windowLevelsDB(x, window: Int(30 * sr), count: 20)
        let median = levels.sorted()[10]
        for l in levels { #expect(abs(l - median) <= 6) }
        // R1: the plan's "peak <= 2 x the 99th-percentile |x|" fights a felted crackle: sparse
        // Hann-windowed bursts spend most of their samples on the shoulders, so the 99th percentile
        // of |x| sits near a third of a burst's peak whatever is in the signal. What it guards is
        // "no pops hiding in the crackle", so the same ratio is taken on 10 ms RMS windows (the
        // burst scale) where the crackle measures about 1.6 and a pop shows as a multiple of that;
        // and the loudest sample is held under 1.5 x the loudest burst the crackle can make.
        #expect(Double(x.map { abs($0) }.max()!) <= 1.5 * FireSound.crackleGain)
        func windowPeakOverP99(_ y: [Float]) -> Double {
            var w: [Double] = []
            var i = 0
            while i + 441 <= y.count { w.append(rms(y[i..<(i + 441)])); i += 220 }
            w.sort()
            return w.last! / w[Int(Double(w.count) * 0.99)]
        }
        #expect(windowPeakOverP99(x) <= 2)
        // ...and it does discriminate: with the pops on, the same ratio is far above 2.
        let withPops = render({ FireSound(seed: 3, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 600)
        #expect(windowPeakOverP99(withPops) > 3)
    }

    @Test func firePopsAreSoft() {
        for seed in UInt64(0)..<2 {
            let x = render({ FireSound(seed: seed, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 600)
            writeIfListening(x, name: "fire", sr: sr)
            #expect(maxStep(x) <= 0.1)
            #expect(x.map { abs($0) }.max()! <= 0.9)
        }
        // Pops really exist: at full rate the loudest sample exceeds the crackle-only loudest.
        let off = Curve.constant(Sudden(rateScale: 0, gainDB: 0))
        let withPops = render({ FireSound(seed: 1, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 600)
        let without = render({ FireSound(seed: 1, sampleRate: 44100, startSecond: 0, sudden: off) }, seconds: 600)
        #expect(withPops.map { abs($0) }.max()! > 1.5 * without.map { abs($0) }.max()!)
        // The attacks on their own (R1: the plan's step bound on the audio is a level test, as a
        // band-limited noise steps about as far as a hard edge would). With the noise replaced by a
        // constant only the burst and pop envelopes remain; a hard attack steps by a burst's whole
        // amplitude, a Hann one by under 0.5% of it per sample.
        for seed in UInt64(0)..<3 {
            var f = FireSound(seed: seed, sampleRate: sr, startSecond: 0, sudden: full)
            f.envelopeOnly = true
            var p = [Float](repeating: 0, count: Int(600 * sr))
            f.render(into: &p, count: p.count)
            #expect(p.map { abs($0) }.max()! > 0.1)   // the pops are really there
            #expect(maxStep(p) <= 0.005)
        }
        #expect(FireSound.burstLengthRange.lowerBound / 2 >= FireSound.burstAttackMinSeconds)
    }

    @Test func fireSeeksCloseToContinuous() {
        let whole = render({ FireSound(seed: 3, sampleRate: 44100, startSecond: 0, sudden: full) }, seconds: 130)
        let slice = Array(whole[Int(120 * sr)..<Int(130 * sr)])
        let seeked = seekLeadIn({ FireSound(seed: 3, sampleRate: sr, startSecond: $0, sudden: full) }, from: 120, seconds: 10, sr: sr)
        let diff = zip(seeked, slice).map { $0 - $1 }
        #expect(rms(diff[...]) <= rms(slice[...]) * pow(10, -20.0 / 20))
    }
}
