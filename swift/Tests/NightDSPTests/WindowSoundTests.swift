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
}
