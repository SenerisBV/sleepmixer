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
