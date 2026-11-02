import Foundation
import Testing
@testable import NightDSP

private func db(_ x: Double) -> Double { 20 * log10(max(x, 1e-12)) }

private func filtered(_ f: Biquad, _ x: [Float]) -> [Float] {
    var f = f
    return x.map { f.process($0) }
}

@Suite struct PrimitivesTests {
    @Test(arguments: [44100.0, 48000.0])
    func lowpassAttenuatesAboveCutoff(sr: Double) {
        let lp = Biquad.lowpass(cutoff: 1000, sampleRate: sr)
        let pass = filtered(lp, sine(200, seconds: 1, sr: sr))
        let stop = filtered(lp, sine(5000, seconds: 1, sr: sr))
        let ref = rms(sine(200, seconds: 1, sr: sr)[Int(sr / 2)...])
        let passDB = db(rms(pass[Int(sr / 2)...]) / ref)
        let stopDB = db(rms(stop[Int(sr / 2)...]) / ref)
        #expect(abs(passDB) < 1)
        #expect(stopDB < -20)
    }

    @Test func highpassAttenuatesBelowCutoff() {
        let sr = 44100.0
        let hp = Biquad.highpass(cutoff: 300, sampleRate: sr)
        let ref = rms(sine(60, seconds: 1, sr: sr)[Int(sr / 2)...])
        let low = filtered(hp, sine(60, seconds: 1, sr: sr))
        let high = filtered(hp, sine(2000, seconds: 1, sr: sr))
        #expect(db(rms(low[Int(sr / 2)...]) / ref) < -18)
        #expect(abs(db(rms(high[Int(sr / 2)...]) / ref)) < 1)
    }

    @Test func peakingBoostsCenter() {
        let sr = 44100.0
        let pk = Biquad.peaking(center: 1000, q: 1, gainDB: 6, sampleRate: sr)
        let y = filtered(pk, sine(1000, seconds: 1, sr: sr))
        let ref = rms(sine(1000, seconds: 1, sr: sr)[Int(sr / 2)...])
        #expect(abs(db(rms(y[Int(sr / 2)...]) / ref) - 6) < 0.2)
    }

    @Test func setCoefficientsKeepsState() {
        let sr = 44100.0
        var a = Biquad.lowpass(cutoff: 1000, sampleRate: sr)
        for v in sine(300, seconds: 0.1, sr: sr) { _ = a.process(v) }
        var b = a
        b.setCoefficients(from: Biquad.lowpass(cutoff: 1000, sampleRate: sr))
        #expect(a.process(0.5) == b.process(0.5))
        var c = Biquad.lowpass(cutoff: 1000, sampleRate: sr)
        #expect(a.process(0.5) != c.process(0.5))
    }

    @Test func reverbTailMatchesDecay() {
        let sr = 44100.0
        var r = Reverb(sampleRate: sr, seed: 7)
        r.decaySeconds = 2
        let n = Int(3 * sr)
        var out = [Float](repeating: 0, count: n)
        for i in 0..<n { out[i] = r.process(i == 0 ? 1 : 0) }
        #expect(out.allSatisfy { $0.isFinite })
        let head = rms(out[0..<Int(0.1 * sr)])
        let tail = rms(out[Int(1.9 * sr)..<Int(2.1 * sr)])
        let rel = db(tail / head)
        #expect(rel > -75 && rel < -45, "tail relative \(rel) dB")
    }

    private func impulseResponse(sr: Double, decay: Double, seconds: Double) -> [Float] {
        var r = Reverb(sampleRate: sr, seed: 7)
        r.decaySeconds = decay
        let n = Int(seconds * sr)
        return (0..<n).map { r.process($0 == 0 ? 1 : 0) }
    }

    @Test func reverbDecayChangesTail() {
        let sr = 44100.0
        let short = impulseResponse(sr: sr, decay: 1, seconds: 2.2)
        let long = impulseResponse(sr: sr, decay: 3, seconds: 2.2)
        let a = rms(short[Int(1.9 * sr)..<Int(2.1 * sr)])
        let b = rms(long[Int(1.9 * sr)..<Int(2.1 * sr)])
        #expect(db(b / a) > 20, "3 s tail only \(db(b / a)) dB above 1 s tail")
    }

    @Test(arguments: [44100.0, 48000.0, 96000.0])
    func reverbDelaysScaleWithSampleRate(sr: Double) {
        let ir = impulseResponse(sr: sr, decay: 2, seconds: 0.2)
        let first = ir.firstIndex { abs($0) > 1e-6 } ?? -1
        let t = Double(first) / sr
        #expect(t > 0.027 && t < 0.032, "first echo at \(t) s at \(sr) Hz")
    }

    @Test(arguments: [44100.0, 48000.0])
    func bandRatiosMapFrequencies(sr: Double) {
        let low = sine(1000, seconds: 2, sr: sr)
        let high = sine(6000, seconds: 2, sr: sr)
        #expect(Analysis.bandEnergyRatio(high, sampleRate: sr, above: 3000) > 0.99)
        #expect(Analysis.bandEnergyRatio(high, sampleRate: sr, below: 3000) < 0.01)
        #expect(Analysis.bandEnergyRatio(low, sampleRate: sr, above: 3000) < 0.01)
        #expect(Analysis.bandEnergyRatio(low, sampleRate: sr, below: 3000) > 0.99)
        #expect(abs(Analysis.centroidHz(high, sampleRate: sr) - 6000) < 60)
        // Tones close to the split catch a wrong sample-rate mapping.
        #expect(Analysis.bandEnergyRatio(sine(3150, seconds: 2, sr: sr), sampleRate: sr, above: 3000) > 0.99)
        #expect(Analysis.bandEnergyRatio(sine(2850, seconds: 2, sr: sr), sampleRate: sr, below: 3000) > 0.99)
        // 1 kHz at amplitude 2 plus 6 kHz at amplitude 1: power 2 vs 0.5, so 0.2 above.
        let mix = zip(low, high).map { 2 * $0 + $1 }
        let r = Analysis.bandEnergyRatio(mix, sampleRate: sr, above: 3000)
        #expect(abs(r - 0.2) < 0.02, "mix ratio \(r)")
        // Length not a multiple of the 4096 window.
        let odd = Array(mix[0..<(Int(sr) + 1234)])
        let ro = Analysis.bandEnergyRatio(odd, sampleRate: sr, above: 3000)
        #expect(abs(ro - 0.2) < 0.02, "odd-length ratio \(ro)")
    }

    @Test func shortBuffersReturnZero() {
        let s = sine(1000, seconds: 0.05, sr: 44100)  // 2205 samples < 4096
        #expect(s.count < 4096)
        #expect(Analysis.centroidHz(s, sampleRate: 44100) == 0)
        #expect(Analysis.bandEnergyRatio(s, sampleRate: 44100, above: 500) == 0)
        #expect(Analysis.bandEnergyRatio(s, sampleRate: 44100, below: 500) == 0)
    }

    @Test func attackDecayIsSoft() {
        #expect(Envelope.attackDecay(t: 0, attack: 0.02, decay: 1) == 0)
        #expect(abs(Envelope.attackDecay(t: 0.01, attack: 0.02, decay: 1) - 0.5) < 0.01)
        #expect(Envelope.attackDecay(t: 0.02, attack: 0.02, decay: 1) == 1)
        var prev = 0.0
        for i in 0...200 {
            let v = Envelope.attackDecay(t: 0.02 * Double(i) / 200, attack: 0.02, decay: 1)
            #expect(v >= prev)
            prev = v
        }
        #expect(Envelope.attackDecay(t: -1, attack: 0.02, decay: 1) == 0)
        #expect(Envelope.raisedCosine(-1) == 0 && Envelope.raisedCosine(2) == 1)
    }

    @Test func analysisAgrees() {
        let sr = 44100.0
        let s = sine(1000, seconds: 2, sr: sr)
        #expect(abs(Analysis.centroidHz(s, sampleRate: sr) - 1000) < 30)
        #expect(abs(Analysis.rmsDB(s[0...]) - (-3.01)) < 0.05)
        #expect(abs(Analysis.peakDB(s)) < 0.01)
        #expect(Analysis.bandEnergyRatio(s, sampleRate: sr, above: 3000) < 0.01)
        #expect(Analysis.bandEnergyRatio(s, sampleRate: sr, below: 3000) > 0.99)
    }

    @Test func wavRoundTrip() throws {
        let samples = (0..<1000).map { Float(sin(Double($0) * 0.05)) * 0.5 }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("rt-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: url) }
        try WAVWriter.write(samples, sampleRate: 48000, to: url)
        let d = try Data(contentsOf: url)
        func u16(_ o: Int) -> Int { Int(d[o]) | Int(d[o + 1]) << 8 }
        func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
        #expect(String(decoding: d[0..<4], as: UTF8.self) == "RIFF")
        #expect(String(decoding: d[8..<12], as: UTF8.self) == "WAVE")
        #expect(u16(20) == 3)
        #expect(u16(22) == 1)
        #expect(u32(24) == 48000)
        let payload = d[44...]
        #expect(payload.count == 4000)
        let back = payload.withUnsafeBytes { raw in
            (0..<1000).map { Float(bitPattern: raw.loadUnaligned(fromByteOffset: $0 * 4, as: UInt32.self).littleEndian) }
        }
        #expect(back == samples)
    }

    @Test func seekLeadInDropsLead() {
        // A pass-through source emitting its absolute sample index proves the offset.
        struct Ramp: SoundSource {
            var n: Int
            mutating func render(into out: inout [Float], count: Int) {
                for i in 0..<count { out[i] = Float(n + i) }
            }
        }
        let y = seekLeadIn({ Ramp(n: Int($0 * 1000)) }, from: 10, seconds: 0.01, sr: 1000)
        #expect(y.first == 10000 && y.count == 10)
    }
}
