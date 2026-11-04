import Foundation

/// The window's weather for one night. Chosen once per night from its seed.
public enum WindowNight: String, CaseIterable, Sendable {
    case rain, rainThunder, cricketsStream, fire
}

/// How the sudden sounds (thunder, fire pops) stand right now.
/// `rateScale` multiplies their event rate (1 = full, 0 = silent);
/// `gainDB` is their gain offset.
public struct Sudden: Equatable, Sendable {
    public var rateScale: Double
    public var gainDB: Double
    public init(rateScale: Double, gainDB: Double) {
        self.rateScale = rateScale
        self.gainDB = gainDB
    }
}

/// The window's rules: which weather a night gets, and how sudden sounds recede.
/// All values are placeholders pending listening (see docs/project-state.md, "Plan 10").
public enum Weather {
    /// Sudden sounds are gone when the drift's ratchet reaches this (about 4 h in).
    static let silentRatchet = 0.6
    /// Sudden-sound gain just before silence.
    static let suddenFloorDB = -18.0

    /// NightRandom stream for the night draw. Streams 40/50/51 are taken by Drift and StationProgram.
    static let nightStream: UInt64 = 70

    /// Cumulative night weights: rain 0.3, rainThunder 0.25, cricketsStream 0.25, fire 0.2.
    static let nightWeights: [(WindowNight, Double)] = [
        (.rain, 0.30), (.rainThunder, 0.25), (.cricketsStream, 0.25), (.fire, 0.20),
    ]

    /// This night's weather. Deterministic in `seed`.
    public static func night(seed: UInt64) -> WindowNight {
        let u = NightRandom.unit(seed, nightStream, 0)
        var acc = 0.0
        for (night, weight) in nightWeights {
            acc += weight
            if u < acc { return night }
        }
        return nightWeights[nightWeights.count - 1].0
    }

    /// Sudden-sound state from the drift's trend alone. Reads only `ratchet`, so it never comes back.
    public static func sudden(_ l: DriftLevel) -> Sudden {
        let r = clamped(l.ratchet / silentRatchet, 0, 1)
        return Sudden(rateScale: 1 - r, gainDB: suddenFloorDB * r)
    }

    /// Sudden-sound state at `t` seconds since switch-on.
    public static func sudden(secondsSinceOn t: Double, seed: UInt64) -> Sudden {
        sudden(Drift.level(clock: t, seed: seed))
    }
}
