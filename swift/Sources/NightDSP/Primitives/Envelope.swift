import Foundation

public enum Envelope {
    /// 0 to 1 over t in [0, 1], clamped outside.
    public static func raisedCosine(_ t: Double) -> Double {
        let c = min(max(t, 0), 1)
        return 0.5 - 0.5 * cos(Double.pi * c)
    }

    /// 0 before t = 0, raised-cosine rise over `attack`, then exp(-(t - attack) / decay).
    public static func attackDecay(t: Double, attack: Double, decay: Double) -> Double {
        if t <= 0 { return 0 }
        if t < attack { return raisedCosine(t / attack) }
        return exp(-(t - attack) / max(decay, 1e-9))
    }
}
