import Foundation

/// The one specified generator: SplitMix64 over a combined (seed, stream, index) key.
/// Identical on every device, so a night is reproducible from its seed.
public enum NightRandom {
    public static func hash(_ seed: UInt64, _ stream: UInt64, _ index: UInt64) -> UInt64 {
        var z = seed &+ 0x9E3779B97F4A7C15 &* (stream &+ 1)
        z ^= index &* 0xD1B54A32D192ED03
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }

    /// Uniform in [0, 1).
    public static func unit(_ seed: UInt64, _ stream: UInt64, _ index: UInt64) -> Double {
        Double(hash(seed, stream, index) >> 11) * 0x1p-53
    }

    /// Uniform in [-1, 1).
    public static func signed(_ seed: UInt64, _ stream: UInt64, _ index: UInt64) -> Double {
        unit(seed, stream, index) * 2 - 1
    }
}
