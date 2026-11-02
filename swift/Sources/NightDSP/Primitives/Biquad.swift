import Foundation

/// RBJ cookbook biquad, transposed direct form II.
public struct Biquad {
    private var b0 = 1.0, b1 = 0.0, b2 = 0.0, a1 = 0.0, a2 = 0.0
    private var z1 = 0.0, z2 = 0.0

    private init(b0: Double, b1: Double, b2: Double, a0: Double, a1: Double, a2: Double) {
        self.b0 = b0 / a0; self.b1 = b1 / a0; self.b2 = b2 / a0
        self.a1 = a1 / a0; self.a2 = a2 / a0
    }

    public static func lowpass(cutoff: Double, q: Double = 0.7071, sampleRate: Double) -> Biquad {
        let (c, alpha) = terms(cutoff, q, sampleRate)
        return Biquad(b0: (1 - c) / 2, b1: 1 - c, b2: (1 - c) / 2, a0: 1 + alpha, a1: -2 * c, a2: 1 - alpha)
    }

    public static func highpass(cutoff: Double, q: Double = 0.7071, sampleRate: Double) -> Biquad {
        let (c, alpha) = terms(cutoff, q, sampleRate)
        return Biquad(b0: (1 + c) / 2, b1: -(1 + c), b2: (1 + c) / 2, a0: 1 + alpha, a1: -2 * c, a2: 1 - alpha)
    }

    /// Constant 0 dB peak gain at `center`.
    public static func bandpass(center: Double, q: Double, sampleRate: Double) -> Biquad {
        let (c, alpha) = terms(center, q, sampleRate)
        return Biquad(b0: alpha, b1: 0, b2: -alpha, a0: 1 + alpha, a1: -2 * c, a2: 1 - alpha)
    }

    public static func peaking(center: Double, q: Double, gainDB: Double, sampleRate: Double) -> Biquad {
        let (c, alpha) = terms(center, q, sampleRate)
        let a = pow(10, gainDB / 40)
        return Biquad(b0: 1 + alpha * a, b1: -2 * c, b2: 1 - alpha * a,
                      a0: 1 + alpha / a, a1: -2 * c, a2: 1 - alpha / a)
    }

    /// cos(w0) and alpha; the frequency is kept below Nyquist so coefficients stay stable.
    private static func terms(_ hz: Double, _ q: Double, _ sr: Double) -> (Double, Double) {
        let w0 = 2 * Double.pi * min(max(hz, 1), sr * 0.49) / sr
        return (cos(w0), sin(w0) / (2 * max(q, 0.01)))
    }

    public mutating func process(_ x: Float) -> Float {
        let xd = Double(x)
        let y = b0 * xd + z1
        z1 = b1 * xd - a1 * y + z2
        z2 = b2 * xd - a2 * y
        return Float(y)
    }

    /// Adopts the coefficients of `other`, keeping this filter's state (for glitch-free sweeps).
    public mutating func setCoefficients(from other: Biquad) {
        b0 = other.b0; b1 = other.b1; b2 = other.b2; a1 = other.a1; a2 = other.a2
    }
}
