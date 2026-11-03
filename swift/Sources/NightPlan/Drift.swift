import Foundation

/// How deep the night has drifted. `free` wanders (a slow cycle rides on the trend);
/// `ratchet` is the trend alone and never falls.
public struct DriftLevel: Equatable, Sendable {
    public var free: Double
    public var ratchet: Double
    public init(free: Double, ratchet: Double) { self.free = free; self.ratchet = ratchet }
    public static let zero = DriftLevel(free: 0, ratchet: 0)
}

/// The drift curves. All values are placeholders pending listening (see docs/project-state.md, "Plan 9").
public enum Drift {
    static let trendStart = 1800.0, trendEnd = 21600.0, trendMax = 0.85
    static let cyclePeriod = 5400.0, cycleAmplitude = 0.10

    /// Drift at `clock` seconds since the listener last settled.
    public static func level(clock: Double, seed: UInt64) -> DriftLevel {
        let c = clock.isNaN ? 0 : max(0, clock)
        let x = clamped((c - trendStart) / (trendEnd - trendStart), 0, 1)
        let trend = trendMax * (3 * x * x - 2 * x * x * x)
        let phase = 2 * Double.pi * NightRandom.unit(seed, 40, 0)
        let amp = cycleAmplitude * min(1, trend / 0.3)
        let cycle = amp * sin(2 * Double.pi * c / cyclePeriod + phase)
        return DriftLevel(free: clamped(trend + cycle, 0, 1), ratchet: trend)
    }

    public static func bedWarp(_ l: DriftLevel) -> WarpDepth {
        let f = l.free
        return WarpDepth(distance: 0.7 * f, slowness: 0.8 * f,
                         fragmentation: 0.6 * max(0, (f - 0.35) / 0.65),
                         proportion: 0.5 * f, ring: 0.3, softness: 0.5 + 0.5 * f, vibrato: 0.2)
    }

    public static func voiceDistance(_ l: DriftLevel) -> Double { clamped(l.free, 0, 1) }
    public static func voiceGainDB(_ l: DriftLevel) -> Double { -14 * l.ratchet }

    public static func channel(_ l: DriftLevel) -> ChannelSettings {
        ChannelSettings(lowCornerHz: 180 + 120 * l.ratchet, highCornerHz: 4500 - 3000 * l.ratchet,
                        hissLevelDB: -48 + 6 * l.ratchet, crackleLevelDB: -54,
                        fadeDepth: 0.25 + 0.45 * l.free, fadeRateHz: 0.05, squash: 0.5)
    }

    public static func staticGainDB(_ l: DriftLevel) -> Double { -12 * l.ratchet }
    public static func segmentGap(_ l: DriftLevel) -> Double { 3 + 480 * pow(clamped(l.free, 0, 1), 1.5) }
    public static func endWait(_ l: DriftLevel) -> Double { 30 + 1200 * clamped(l.free, 0, 1) }
}
