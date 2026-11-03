import Testing
import Foundation
import NightDSP
import NightPlan
@testable import NightRadio

private let sr = 44100.0
private let fileRate = 22050.0
private let amp = pow(10, -24.0 / 20) * 2.0.squareRoot()

/// A temp bundle whose segment files hold `samples(fileIndex)` but whose manifest says `seconds` each.
private func bundle(files: Int, seconds: Double, _ samples: (Int) -> [Float]) throws -> StationBundle {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("night-voice-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    var segs = [String]()
    for k in 0..<files {
        let name = String(format: "s%02d.wav", k + 1)
        try WAVWriter.write(samples(k), sampleRate: Int(fileRate), to: dir.appendingPathComponent(name))
        segs.append("{\"file\": \"\(name)\", \"seconds\": \(seconds)}")
    }
    let json = "{\"id\": \"t\", \"title\": \"T\", \"segments\": [\(segs.joined(separator: ","))]}"
    try Data(json.utf8).write(to: dir.appendingPathComponent("station.json"))
    return try StationBundle.load(directory: dir)
}

private func tone(seconds: Double, ramp: Bool) -> [Float] {
    let n = Int(seconds * fileRate)
    return (0..<n).map { i in
        let a = ramp ? amp * Double(i) / Double(n) : amp
        return Float(a * sin(2 * Double.pi * 300 * Double(i) / fileRate))
    }
}

private func render(_ v: inout StationVoice, seconds: Double) -> [Float] {
    let total = Int(seconds * sr)
    var out = [Float](), buf = [Float](repeating: 0, count: 2048)
    out.reserveCapacity(total)
    while out.count < total {
        let n = min(2048, total - out.count)
        v.render(into: &buf, count: n)
        out.append(contentsOf: buf[0..<n])
    }
    return out
}

private func firstSeed(segments: [Double], level: DriftLevel, where ok: (ScheduledSegment) -> Bool) -> UInt64 {
    for seed in UInt64(1)... {
        var p = StationProgram(segmentSeconds: segments, seed: seed, level: { _ in level })
        if let s = p.segment(at: 0), ok(s) { return seed }
    }
    fatalError()
}

private func rms(_ x: ArraySlice<Float>) -> Double {
    (x.reduce(0.0) { $0 + Double($1) * Double($1) } / Double(max(x.count, 1))).squareRoot()
}

/// Drift free 0.05: the gap is 3 + 480 * 0.05^1.5 = 8.37 s, not a whole number of seconds, so every
/// segment after the first is revealed after its (backdated) start. Each must still begin at clip
/// time 0: the files ramp from silence to full over 3 s, so a clip entered late is loud at once.
@Test func lateRevealedSegmentsStartFromTheClipHead() throws {
    let level = DriftLevel(free: 0.05, ratchet: 0)
    let b = try bundle(files: 3, seconds: 3) { _ in tone(seconds: 3, ramp: true) }
    let seed = firstSeed(segments: [3, 3, 3], level: level) { $0.index == 0 }
    var v = StationVoice(bundle: b, programSeed: seed, distanceSeed: 1, level: { _ in level },
                         sampleRate: sr, loader: { try? VoiceClip.load(url: $0) })
    let out = render(&v, seconds: 30)

    // Onsets: the first audible sample after at least 1 s of silence.
    var onsets = [Int](), quiet = 0
    for (i, x) in out.enumerated() {
        if abs(x) < 1e-6 { quiet += 1; continue }
        if quiet >= Int(sr) { onsets.append(i) }
        quiet = 0
    }
    #expect(onsets.count == 2, "onsets \(onsets.map { Double($0) / sr })")
    for o in onsets {
        let head = rms(out[o..<min(o + Int(0.05 * sr), out.count)])
        #expect(head < 0.02 * amp, "onset at \(Double(o) / sr) s: head RMS \(head / amp) of full")
        // ...and it is the clip that plays: by 2.5 s in, the ramp is well up.
        let later = rms(out[(o + Int(2.4 * sr))..<(o + Int(2.5 * sr))])
        #expect(later > 0.4 * amp, "onset at \(Double(o) / sr) s: later RMS \(later / amp)")
    }
}

/// At switch-on the program is mid-segment: the clip is seeked but must fade in, not start at full level.
@Test func switchOnFadesIn() throws {
    let b = try bundle(files: 2, seconds: 3) { _ in tone(seconds: 3, ramp: false) }
    let seed = firstSeed(segments: [3, 3], level: .zero) { $0.start < -0.5 }
    var v = StationVoice(bundle: b, programSeed: seed, distanceSeed: 1, level: { _ in .zero },
                         sampleRate: sr, loader: { try? VoiceClip.load(url: $0) })
    let out = render(&v, seconds: 0.5)
    let firstMs = Double(out[0..<Int(0.001 * sr)].map { abs($0) }.max()!)
    #expect(firstMs < 0.1 * amp, "first ms peak \(firstMs / amp) of full")
    #expect(rms(out[Int(0.1 * sr)..<Int(0.2 * sr)]) > 0.5 * amp)
}

/// Clips longer than their scheduled seconds: the next segment starts while the last still plays.
/// The old clip fades out; the output never jumps (a 300 Hz tone moves at most ~0.04 * amp a sample).
@Test func overrunningClipFadesOut() throws {
    let b = try bundle(files: 2, seconds: 3) { _ in tone(seconds: 12, ramp: false) }
    let seed = firstSeed(segments: [3, 3], level: .zero) { $0.index == 0 }
    var v = StationVoice(bundle: b, programSeed: seed, distanceSeed: 1, level: { _ in .zero },
                         sampleRate: sr, loader: { try? VoiceClip.load(url: $0) })
    let out = render(&v, seconds: 12)
    var worst = 0.0, at = 0
    for i in 1..<out.count where Double(abs(out[i] - out[i - 1])) > worst {
        worst = Double(abs(out[i] - out[i - 1])); at = i
    }
    #expect(worst < 0.15 * amp, "largest step \(worst / amp) of full at \(Double(at) / sr) s")
}
