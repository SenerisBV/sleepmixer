import Foundation
import NightDSP
import NightPlan

func rms(_ x: ArraySlice<Float>) -> Double {
    guard !x.isEmpty else { return 0 }
    var s = 0.0
    for v in x { s += Double(v) * Double(v) }
    return (s / Double(x.count)).squareRoot()
}

func sine(_ hz: Double, seconds: Double, sr: Double) -> [Float] {
    let n = Int(seconds * sr)
    return (0..<n).map { Float(sin(2 * Double.pi * hz * Double($0) / sr)) }
}

func noise(seconds: Double, sr: Double, seed: UInt64) -> [Float] {
    let n = Int(seconds * sr)
    return (0..<n).map { Float(NightRandom.signed(seed, 0, UInt64($0))) }
}

let seekLeadInSeconds = 6.0

/// Builds a source at max(0, from - 6), renders lead + seconds, drops the lead.
func seekLeadIn<S: SoundSource>(_ make: (Double) -> S, from: Double, seconds: Double, sr: Double) -> [Float] {
    let start = max(0, from - seekLeadInSeconds)
    let lead = Int(((from - start) * sr).rounded())
    let count = lead + Int(seconds * sr)
    var source = make(start)
    var out = [Float](repeating: 0, count: count)
    source.render(into: &out, count: count)
    return Array(out[lead...])
}

/// Processor variant: `input` is the full signal starting at `inputStart` seconds.
/// The processor is built at max(0, from - 6) and fed the signal from there.
func seekLeadIn<P: Processor>(
    _ make: (Double) -> P, input: [Float], inputStart: Double = 0,
    from: Double, seconds: Double, sr: Double
) -> [Float] {
    let start = max(0, from - seekLeadInSeconds)
    let lead = Int(((from - start) * sr).rounded())
    let first = Int(((start - inputStart) * sr).rounded())
    let count = lead + Int(seconds * sr)
    var buffer = Array(input[first..<(first + count)])
    var processor = make(start)
    processor.process(&buffer, count: count)
    return Array(buffer[lead...])
}

func writeIfListening(_ x: [Float], name: String, sr: Double) {
    guard let dir = ProcessInfo.processInfo.environment["NIGHT_LISTEN_DIR"], !dir.isEmpty else { return }
    let url = URL(fileURLWithPath: dir).appendingPathComponent("\(name).wav")
    try? WAVWriter.write(x, sampleRate: Int(sr), to: url)
}
