import Foundation

/// Plays a decoded file as a source, from `startSecond` of the file (so seeking is exact: the
/// output depends only on absolute time). Linear resampling when the rates differ. After the end
/// it is silent, preceded by a 50 ms raised-cosine fade over the file's last 50 ms, so it never
/// stops on a click.
public struct FileSource: SoundSource {
    public static let fadeSeconds = 0.05
    let samples: [Float]
    let fileRate: Double
    let sampleRate: Double
    var frame: Int
    let startFrame: Int

    public init(samples: [Float], fileSampleRate: Double, sampleRate: Double, startSecond: Double) {
        self.samples = samples
        self.fileRate = fileSampleRate
        self.sampleRate = sampleRate
        self.startFrame = Int((max(0, startSecond.isFinite ? startSecond : 0) * sampleRate).rounded())
        self.frame = startFrame
    }

    public mutating func render(into out: inout [Float], count: Int) {
        let n = samples.count
        let duration = Double(n) / fileRate
        let fadeStart = duration - Self.fadeSeconds
        for i in 0..<count {
            let t = Double(frame + i) / sampleRate
            guard n > 0, t < duration else { out[i] = 0; continue }
            let pos = t * fileRate
            let i0 = min(Int(pos), n - 1)
            let i1 = min(i0 + 1, n - 1)
            let frac = Float(pos - Double(i0))
            var v = samples[i0] + (samples[i1] - samples[i0]) * frac
            if t > fadeStart {
                v *= Float(0.5 * (1 + cos(Double.pi * (t - fadeStart) / Self.fadeSeconds)))
            }
            out[i] = v
        }
        frame += count
    }
}
