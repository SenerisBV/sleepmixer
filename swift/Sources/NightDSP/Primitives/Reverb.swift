import Foundation
import NightPlan

/// Small Schroeder reverb: 4 parallel combs into 2 series allpasses. Returns the wet signal only.
/// Delay lengths are defined in seconds, so they scale with the sample rate.
public struct Reverb {
    // Placeholder base delays (seconds); each is jittered +-5% by the seed.
    private static let combSeconds = [0.0297, 0.0371, 0.0411, 0.0437]
    private static let allpassSeconds = [0.0050, 0.0017]

    private struct Comb {
        var buf: [Float]
        var pos = 0
        var feedback: Float = 0
        var damped: Float = 0
        var delaySeconds: Double
    }
    private var combs: [Comb]
    private var allpasses: [(buf: [Float], pos: Int)]

    public var decaySeconds: Double {
        didSet { updateFeedback() }
    }

    public init(sampleRate: Double, seed: UInt64) {
        combs = Self.combSeconds.enumerated().map { i, s in
            let secs = s * (1 + 0.05 * NightRandom.signed(seed, 0x5265, UInt64(i)))
            return Comb(buf: [Float](repeating: 0, count: max(1, Int((secs * sampleRate).rounded()))), delaySeconds: secs)
        }
        allpasses = Self.allpassSeconds.map { (Array(repeating: 0, count: max(1, Int(($0 * sampleRate).rounded()))), 0) }
        decaySeconds = 2
        updateFeedback()
    }

    private mutating func updateFeedback() {
        let d = max(decaySeconds, 0.05)
        for i in combs.indices {
            // RT60: the loop loses 60 dB every `decaySeconds`.
            combs[i].feedback = Float(pow(10, -3 * combs[i].delaySeconds / d))
        }
    }

    public mutating func process(_ x: Float) -> Float {
        var sum: Float = 0
        for i in combs.indices {
            let out = combs[i].buf[combs[i].pos]
            // One-pole damping in the loop keeps the tail from ringing metallically.
            combs[i].damped = out * 0.7 + combs[i].damped * 0.3
            combs[i].buf[combs[i].pos] = x + combs[i].damped * combs[i].feedback
            combs[i].pos += 1
            if combs[i].pos == combs[i].buf.count { combs[i].pos = 0 }
            sum += out
        }
        var y = sum * 0.25
        for i in allpasses.indices {
            let delayed = allpasses[i].buf[allpasses[i].pos]
            let v = y + delayed * 0.5
            allpasses[i].buf[allpasses[i].pos] = v
            y = delayed - v * 0.5
            allpasses[i].pos += 1
            if allpasses[i].pos == allpasses[i].buf.count { allpasses[i].pos = 0 }
        }
        return y
    }
}
