import Foundation
import NightPlan

/// "Another room": a lowpass that closes, a quieter direct sound and a bigger, longer reverb.
///
/// The distance depth is read every 512 frames (on the absolute-frame grid) and glided with a
/// one-pole smoother. Gains and reverb send move per sample between block values; the filter
/// corner moves per block (smoothed already, so a 512-frame step is inaudible). Stateful, so a
/// seek is approximate: start it a few seconds early and discard the lead-in.
public struct Distance: Processor {
    // Brief values (placeholders recorded in Task 8)
    static let blockFrames = 512
    static let glideSeconds = 2.0
    static let openHz = 8000.0
    static let closedHz = 400.0
    static let directLoss = 0.8
    static let sendBase = 0.15, sendSpan = 0.7
    static let decayBase = 1.2, decaySpan = 3.3

    // Invented
    static let reverbSeedSalt: UInt64 = 0xD157
    static let q = 0.7071

    private let sampleRate: Double
    private let warp: Curve<WarpDepth>
    private let startFrame: Int
    private var frame: Int
    private var prevDepth: Double
    private var depth: Double
    private var filter: Biquad
    private var reverb: Reverb

    public init(sampleRate: Double, seed: UInt64, warp: Curve<WarpDepth>, startSecond: Double) {
        self.sampleRate = sampleRate
        self.warp = warp
        startFrame = Int((startSecond * sampleRate).rounded())
        frame = startFrame
        let d0 = warp(Double(startFrame) / sampleRate).distance
        prevDepth = d0
        depth = d0
        filter = Biquad.lowpass(cutoff: Self.corner(d0), q: Self.q, sampleRate: sampleRate)
        reverb = Reverb(sampleRate: sampleRate, seed: seed ^ Self.reverbSeedSalt)
        reverb.decaySeconds = Self.decayBase + Self.decaySpan * d0
    }

    static func corner(_ d: Double) -> Double { openHz * pow(closedHz / openHz, d) }

    /// The smoothed depth after the update at `boundary` (an absolute frame on the 512 grid).
    private func glided(_ d: Double, boundary: Int) -> Double {
        let target = warp(Double(boundary) / sampleRate).distance
        let a = 1 - exp(-Double(Self.blockFrames) / (Self.glideSeconds * sampleRate))
        return d + a * (target - d)
    }

    /// The lowpass corner in effect at `second`, replaying the smoother from this processor's start.
    public func cornerHz(at second: Double) -> Double {
        let f = Int((second * sampleRate).rounded())
        var d = warp(Double(startFrame) / sampleRate).distance
        var b = (startFrame / Self.blockFrames + 1) * Self.blockFrames
        while b <= f {
            d = glided(d, boundary: b)
            b += Self.blockFrames
        }
        return Self.corner(d)
    }

    public mutating func process(_ buffer: inout [Float], count: Int) {
        for i in 0..<count {
            if frame % Self.blockFrames == 0 && frame > startFrame {
                prevDepth = depth
                depth = glided(depth, boundary: frame)
                filter.setCoefficients(from: Biquad.lowpass(cutoff: Self.corner(depth), q: Self.q, sampleRate: sampleRate))
                reverb.decaySeconds = Self.decayBase + Self.decaySpan * depth
            }
            let u = Double(frame % Self.blockFrames) / Double(Self.blockFrames)
            let d = prevDepth + (depth - prevDepth) * u
            let direct = Float(1 - Self.directLoss * d)
            let send = Float(Self.sendBase + Self.sendSpan * d)
            let lp = filter.process(buffer[i])
            buffer[i] = direct * lp + reverb.process(send * lp)
            frame += 1
        }
    }
}
