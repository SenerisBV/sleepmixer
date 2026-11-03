import Testing
import Foundation
import Synchronization
import NightDSP
import NightPlan
@testable import NightRadio

private let sr = 44100.0
private let block = 2048
private let toneHz = 300.0
private let recipe = StationRecipe.all[0]

/// A temp station bundle: two 3 s segments of a 300 Hz tone at -24 dBFS RMS, 22050 Hz.
private func makeBundle() throws -> URL {
    let dir = FileManager.default.temporaryDirectory
        .appendingPathComponent("night-radio-\(UUID().uuidString)").appendingPathComponent(recipe.id)
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let fileRate = 22050.0
    let amp = pow(10, -24.0 / 20) * 2.0.squareRoot()
    let tone = (0..<Int(3 * fileRate)).map { Float(amp * sin(2 * Double.pi * toneHz * Double($0) / fileRate)) }
    try WAVWriter.write(tone, sampleRate: 22050, to: dir.appendingPathComponent("s01.wav"))
    try WAVWriter.write(tone, sampleRate: 22050, to: dir.appendingPathComponent("s02.wav"))
    let json = """
    {"id": "\(recipe.id)", "title": "\(recipe.title)",
     "segments": [{"file": "s01.wav", "seconds": 3.0}, {"file": "s02.wav", "seconds": 3.0}]}
    """
    try Data(json.utf8).write(to: dir.appendingPathComponent("station.json"))
    return dir
}

private func clock(_ seed: UInt64) -> DriftClock {
    let c = DriftClock(seed: seed)
    c.touch(at: 0)
    return c
}

private func render<S: SoundSource>(_ s: inout S, seconds: Double) -> [Float] {
    let total = Int(seconds * sr)
    var out = [Float]()
    out.reserveCapacity(total)
    var buf = [Float](repeating: 0, count: block)
    var done = 0
    while done < total {
        let n = min(block, total - done)
        s.render(into: &buf, count: n)
        out.append(contentsOf: buf[0..<n])
        done += n
    }
    return out
}

/// Power at `hz` (single-bin DFT, Hann window) per sample, in dB.
private func toneDB(_ x: ArraySlice<Float>, hz: Double) -> Double {
    let n = x.count
    var re = 0.0, im = 0.0
    for (i, v) in x.enumerated() {
        let w = 0.5 - 0.5 * cos(2 * Double.pi * Double(i) / Double(n))
        let a = 2 * Double.pi * hz * Double(i) / sr
        re += Double(v) * w * cos(a)
        im -= Double(v) * w * sin(a)
    }
    return 10 * log10(max((re * re + im * im) / Double(n * n), 1e-30))
}

/// The voice band 290-310 Hz: the strongest of a few bins across it.
private func voiceBandDB(_ x: ArraySlice<Float>) -> Double {
    stride(from: 290.0, through: 310.0, by: 5.0).map { toneDB(x, hz: $0) }.max()!
}

/// The first seed whose program starts in segment 0.
private func seedStartingInSegmentZero() -> UInt64 {
    for seed in UInt64(1)... {
        var p = StationProgram(segmentSeconds: [3, 3], seed: StationChain.programSeed(seed, recipe: recipe),
                               level: { _ in .zero })
        if p.segment(at: 0)?.index == 0 { return seed }
    }
    fatalError()
}

@Test func bundleLoadsStationJSON() throws {
    let dir = try makeBundle()
    let b = try StationBundle.load(directory: dir)
    #expect(b.id == recipe.id)
    #expect(b.title == recipe.title)
    #expect(b.segmentSeconds == [3, 3])
    #expect(b.segmentURLs.map(\.lastPathComponent) == ["s01.wav", "s02.wav"])
}

@Test func voiceIsAboveBedEarly() throws {
    let bundle = try StationBundle.load(directory: try makeBundle())
    let seed = seedStartingInSegmentZero()
    var withVoice = StationChain(recipe: recipe, bundle: bundle, seed: seed, clock: clock(seed), sampleRate: sr)
    var bedOnly = StationChain(recipe: recipe, bundle: nil, seed: seed, clock: clock(seed), sampleRate: sr)
    let a = render(&withVoice, seconds: 6)
    let b = render(&bedOnly, seconds: 6)

    // Where speech plays in 0-6 s, from the same program the chain uses.
    var p = StationProgram(segmentSeconds: [3, 3], seed: StationChain.programSeed(seed, recipe: recipe),
                           level: { _ in .zero })
    var speech = [Bool](repeating: false, count: a.count)
    for i in stride(from: 0, to: a.count, by: 1) { speech[i] = p.segment(at: Double(i) / sr) != nil }
    let va = a.indices.filter { speech[$0] }.map { a[$0] }
    let vb = b.indices.filter { speech[$0] }.map { b[$0] }
    #expect(va.count > Int(sr))
    let diff = Analysis.rmsDB(va[...]) - Analysis.rmsDB(vb[...])
    print("voiceIsAboveBedEarly: voice over bed \(diff) dB")
    #expect(diff >= 6, "voice over bed: \(diff) dB")
}

@Test func missingSegmentIsSilence() throws {
    let bundle = try StationBundle.load(directory: try makeBundle())
    let seed = seedStartingInSegmentZero()
    var missing = StationChain(recipe: recipe, bundle: bundle, seed: seed, clock: clock(seed), sampleRate: sr,
                               loader: { _ in nil })
    var bedOnly = StationChain(recipe: recipe, bundle: nil, seed: seed, clock: clock(seed), sampleRate: sr)
    var present = StationChain(recipe: recipe, bundle: bundle, seed: seed, clock: clock(seed), sampleRate: sr)
    let m = render(&missing, seconds: 10)
    let b = render(&bedOnly, seconds: 10)
    let v = render(&present, seconds: 10)
    #expect(!m.contains { !$0.isFinite })
    #expect(m.map { abs($0) }.max()! <= 0.8912509)
    // The measure sees the voice when it plays, and the missing render has none of it.
    let window = 0..<Int(2.5 * sr)
    print("missingSegmentIsSilence: voice band dB present \(voiceBandDB(v[window])), bed \(voiceBandDB(b[window])), missing \(voiceBandDB(m[window]))")
    #expect(voiceBandDB(v[window]) > voiceBandDB(b[window]) + 10)
    #expect(voiceBandDB(m[window]) <= voiceBandDB(b[window]) + 1)
    #expect(m == b)
}

@Test func loadsEachSegmentOncePerPlay() throws {
    let bundle = try StationBundle.load(directory: try makeBundle())
    let seed = seedStartingInSegmentZero()
    let loads = Mutex<[String]>([])
    var chain = StationChain(recipe: recipe, bundle: bundle, seed: seed, clock: clock(seed), sampleRate: sr,
                             loader: { url in
                                 loads.withLock { $0.append(url.lastPathComponent) }
                                 return try? VoiceClip.load(url: url)
                             })
    // 0-20 s: segment 0, a 3 s gap, segment 1, then the end-of-recording wait (30 s at drift 0).
    _ = render(&chain, seconds: 20)
    #expect(loads.withLock { $0 } == ["s01.wav", "s02.wav"])
}

@Test func deterministic() throws {
    let bundle = try StationBundle.load(directory: try makeBundle())
    var x = StationChain(recipe: recipe, bundle: bundle, seed: 7, clock: clock(7), sampleRate: sr)
    var y = StationChain(recipe: recipe, bundle: bundle, seed: 7, clock: clock(7), sampleRate: sr)
    #expect(render(&x, seconds: 5) == render(&y, seconds: 5))
}

@Test func staticIsQuietAndContinuous() {
    var s = StaticChain(seed: 3, clock: clock(3), sampleRate: sr)
    let out = render(&s, seconds: 10)
    let level = Analysis.rmsDB(out[...])
    print("staticIsQuietAndContinuous: RMS \(level) dB")
    #expect(level >= -40 && level <= -20, "static RMS \(level) dB")
    for start in stride(from: 0, to: out.count, by: block) {
        let b = out[start..<min(start + block, out.count)]
        #expect(b.contains { $0 != 0 }, "zero block at \(start)")
    }
}

#if !DEBUG
@Test func rendersFastEnough() throws {
    let dir = try makeBundle()
    let bundle = try StationBundle.load(directory: dir)
    let c = clock(11)
    var chains = StationRecipe.all.map {
        StationChain(recipe: $0, bundle: bundle, seed: 11, clock: c, sampleRate: sr)
    }
    var stat = StaticChain(seed: 11, clock: c, sampleRate: sr)
    var buf = [Float](repeating: 0, count: block)
    let seconds = 60.0
    let total = Int(seconds * sr)
    let t0 = ContinuousClock.now
    var done = 0
    while done < total {
        let n = min(block, total - done)
        for i in chains.indices { chains[i].render(into: &buf, count: n) }
        stat.render(into: &buf, count: n)
        done += n
    }
    let elapsed = ContinuousClock.now - t0
    let wall = Double(elapsed.components.seconds) + Double(elapsed.components.attoseconds) * 1e-18
    print("rendersFastEnough: 60 s of 3 stations + static in \(wall) s = \(seconds / wall)x real time")
    #expect(wall < 6, "\(wall) s")
}
#endif
