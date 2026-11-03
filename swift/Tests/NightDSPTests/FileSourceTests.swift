import Foundation
import Testing
import NightDSP
import NightPlan

func fixtureURL(_ name: String) -> URL {
    URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("filesource-\(UUID().uuidString)-\(name)")
}

/// Hand-rolled WAV writer for formats WAVWriter does not produce.
func wavData(format: UInt16, channels: UInt16, rate: UInt32, bits: UInt16, payload: Data,
             extensible: Bool = false, extraChunk: Bool = false) -> Data {
    var d = Data()
    func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
    func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
    var body = Data()
    func b16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { body.append(contentsOf: $0) } }
    func b32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { body.append(contentsOf: $0) } }
    b16(extensible ? 0xFFFE : format); b16(channels); b32(rate)
    b32(rate * UInt32(channels) * UInt32(bits / 8)); b16(channels * bits / 8); b16(bits)
    if extensible {
        b16(22); b16(bits); b32(3)
        b16(format); body.append(contentsOf: [0, 0, 0, 0, 0x10, 0, 0x80, 0, 0, 0xAA, 0, 0x38, 0x9B, 0x71])
    }
    d.append(contentsOf: Array("RIFF".utf8)); u32(0)
    d.append(contentsOf: Array("WAVE".utf8))
    if extraChunk { d.append(contentsOf: Array("LIST".utf8)); u32(3); d.append(contentsOf: [1, 2, 3, 0]) }
    d.append(contentsOf: Array("fmt ".utf8)); u32(UInt32(body.count)); d.append(body)
    d.append(contentsOf: Array("data".utf8)); u32(UInt32(payload.count)); d.append(payload)
    return d
}

func int16Payload(_ xs: [Int16]) -> Data {
    var d = Data()
    for x in xs { withUnsafeBytes(of: x.littleEndian) { d.append(contentsOf: $0) } }
    return d
}

@Suite struct FileSourceTests {
    func tone(_ hz: Double, seconds: Double, rate: Double, amp: Double = 0.5) -> [Float] {
        (0..<Int(seconds * rate)).map { Float(amp * sin(2 * Double.pi * hz * Double($0) / rate)) }
    }

    @Test func wavRoundTrip() throws {
        let x = tone(300, seconds: 0.5, rate: 44100)
        let url = fixtureURL("rt.wav")
        try WAVWriter.write(x, sampleRate: 44100, to: url)
        let r = try WAVReader.read(url: url)
        #expect(r.sampleRate == 44100)
        #expect(r.samples == x)
    }

    @Test func readsInt16AndStereoMixedToMono() throws {
        let url = fixtureURL("s16.wav")
        // L = 16384, R = -16384 -> mono 0 ; L = R = 8192 -> 0.25
        let payload = int16Payload([16384, -16384, 8192, 8192])
        try wavData(format: 1, channels: 2, rate: 48000, bits: 16, payload: payload, extraChunk: true).write(to: url)
        let r = try WAVReader.read(url: url)
        #expect(r.sampleRate == 48000)
        #expect(r.samples == [0, 0.25])
    }

    @Test func readsInt24Int32AndExtensible() throws {
        let u24 = fixtureURL("s24.wav")
        try wavData(format: 1, channels: 1, rate: 44100, bits: 24,
                    payload: Data([0x00, 0x00, 0x40, 0x00, 0x00, 0xC0])).write(to: u24)
        #expect(try WAVReader.read(url: u24).samples == [0.5, -0.5])
        let u32 = fixtureURL("s32.wav")
        var p = Data(); withUnsafeBytes(of: Int32(0x2000_0000).littleEndian) { p.append(contentsOf: $0) }
        try wavData(format: 1, channels: 1, rate: 44100, bits: 32, payload: p).write(to: u32)
        #expect(try WAVReader.read(url: u32).samples == [0.25])
        let ext = fixtureURL("ext.wav")
        var f = Data(); withUnsafeBytes(of: Float(0.125).bitPattern.littleEndian) { f.append(contentsOf: $0) }
        try wavData(format: 3, channels: 1, rate: 44100, bits: 32, payload: f, extensible: true).write(to: ext)
        #expect(try WAVReader.read(url: ext).samples == [0.125])
    }

    @Test func rejectsUnsupported() throws {
        let junk = fixtureURL("junk.wav")
        try Data("not a wav file at all".utf8).write(to: junk)
        #expect(throws: WAVReader.Error.self) { try WAVReader.read(url: junk) }
        let u8 = fixtureURL("u8.wav")
        try wavData(format: 1, channels: 1, rate: 44100, bits: 8, payload: Data([1, 2])).write(to: u8)
        #expect(throws: WAVReader.Error.self) { try WAVReader.read(url: u8) }
        let six = fixtureURL("six.wav")
        try wavData(format: 1, channels: 6, rate: 44100, bits: 16, payload: int16Payload([0, 0, 0, 0, 0, 0])).write(to: six)
        #expect(throws: WAVReader.Error.self) { try WAVReader.read(url: six) }
        #expect(throws: WAVReader.Error.self) { try WAVReader.read(url: fixtureURL("missing.wav")) }
    }

    @Test func resamplingKeepsDurationWithinAFrame() {
        let x = tone(200, seconds: 1, rate: 48000)
        var src = FileSource(samples: x, fileSampleRate: 48000, sampleRate: 44100, startSecond: 0)
        var out = [Float](repeating: 0, count: 2 * 44100)
        src.render(into: &out, count: out.count)
        let lastAudible = out.lastIndex { $0 != 0 } ?? 0
        #expect(abs(Double(lastAudible + 1) - 44100) <= 1.5)
        // The tone survives resampling at the right pitch: compare to a direct 44.1 kHz sine.
        let ref = tone(200, seconds: 0.9, rate: 44100)
        var worst: Float = 0
        for i in 0..<ref.count { worst = max(worst, abs(out[i] - ref[i])) }
        #expect(worst < 0.01, "worst error \(worst)")
    }

    @Test func seekEqualsASliceOfAContinuousRender() {
        let x = tone(173, seconds: 3, rate: 48000)
        var a = FileSource(samples: x, fileSampleRate: 48000, sampleRate: 44100, startSecond: 0)
        var full = [Float](repeating: 0, count: 3 * 44100)
        a.render(into: &full, count: full.count)
        var b = FileSource(samples: x, fileSampleRate: 48000, sampleRate: 44100, startSecond: 1.5)
        var part = [Float](repeating: 0, count: 44100)
        b.render(into: &part, count: part.count)
        #expect(part == Array(full[66150..<(66150 + 44100)]))
    }

    @Test func shortFileEndsInAFadeNotAClick() {
        let rate = 44100.0
        let x = tone(220, seconds: 1, rate: rate)
        var src = FileSource(samples: x, fileSampleRate: rate, sampleRate: rate, startSecond: 0)
        var out = [Float](repeating: 0, count: 2 * 44100)
        src.render(into: &out, count: out.count)
        let fade = Int(0.05 * rate)
        let n = x.count
        // Tapered: the last 50 ms of the file shrink to zero and never exceed the original.
        for i in (n - fade)..<n { #expect(abs(out[i]) <= abs(x[i]) + 1e-6) }
        func peak(_ s: ArraySlice<Float>) -> Float { s.reduce(0) { max($0, abs($1)) } }
        #expect(peak(out[(n - fade)..<(n - fade + 220)]) > 0.4)
        #expect(peak(out[(n - 220)..<n]) < 0.01)
        #expect(out[n...].allSatisfy { $0 == 0 })
        func maxJump(_ s: ArraySlice<Float>) -> Float {
            zip(s, s.dropFirst()).reduce(0) { max($0, abs($1.1 - $1.0)) }
        }
        #expect(maxJump(out[(n - fade - 1)..<out.count]) <= maxJump(x[...]))
    }
}

@Suite struct VoiceFactoryTests {
    func voiceFile(seconds: Double = 40) throws -> URL {
        var rng = UInt64(0)
        let x: [Float] = (0..<Int(seconds * 44100)).map { i in
            let t = Double(i) / 44100
            let env = 0.5 + 0.5 * sin(2 * Double.pi * 0.7 * t)
            rng += 1
            return Float(0.4 * env * (sin(2 * Double.pi * 140 * t) + 0.5 * sin(2 * Double.pi * 910 * t)))
                + Float(0.02 * NightRandom.signed(3, 0, rng))
        }
        let url = fixtureURL("voice.wav")
        try WAVWriter.write(x, sampleRate: 44100, to: url)
        return url
    }

    @Test func voiceThroughTheChannelIsFiniteAndGuarded() throws {
        let url = try voiceFile()
        for channel in [true, false] {
            let out = NightFactory.audition(AuditionRequest(
                scene: .chimes, seconds: 20, startSecond: 3, warp: WarpDepth(distance: 0.5, fragmentation: 0.3),
                channel: channel, voiceFile: url))
            #expect(out.count == 20 * 44100)
            #expect(out.allSatisfy { $0.isFinite })
            let peak = out.reduce(Float(0)) { max($0, abs($1)) }
            #expect(peak <= 0.95 && peak > 0.01, "peak \(peak)")
            #expect(Analysis.rmsDB(out[...]) > -60)
        }
    }

    @Test func voiceSeekingMatchesALongerRender() throws {
        let url = try voiceFile()
        let sr = 44100
        let warp = WarpDepth(distance: 0.5, fragmentation: 0.3)
        let a = NightFactory.audition(AuditionRequest(scene: .chimes, seconds: 40, seed: 7, warp: warp, voiceFile: url))
        let b = NightFactory.audition(AuditionRequest(scene: .chimes, seconds: 20, startSecond: 20, seed: 7, warp: warp, voiceFile: url))
        #expect(b.count == 20 * sr)
        let tail = Array(a[(20 * sr)..<(40 * sr)])
        let head = Array(a[0..<(20 * sr)])
        func residualDB(_ x: [Float], _ y: [Float]) -> Double {
            Analysis.rmsDB(zip(x, y).map { $0 - $1 }[...]) - Analysis.rmsDB(y[...])
        }
        #expect(residualDB(b, tail) <= -90, "seeked voice is only \(residualDB(b, tail)) dB under the tail")
        #expect(residualDB(b, head) >= -10)
    }

    @Test func aFileShorterThanTheRenderEndsInSilence() throws {
        let url = try voiceFile(seconds: 5)
        let out = NightFactory.audition(AuditionRequest(
            scene: .chimes, seconds: 12, seed: 2, channel: false, voiceFile: url))
        #expect(out.count == 12 * 44100)
        #expect(out.allSatisfy { $0.isFinite })
        #expect(Analysis.rmsDB(out[(8 * 44100)...]) < -100)
    }

    @Test func unreadableFileRendersNothing() {
        let out = NightFactory.audition(AuditionRequest(scene: .chimes, voiceFile: fixtureURL("nope.wav")))
        #expect(out.isEmpty)
    }
}
