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
}
