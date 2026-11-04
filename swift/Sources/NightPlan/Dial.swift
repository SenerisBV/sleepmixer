import Foundation

/// What the radio dial is doing at one needle position: each station's gain, the static between, and whether it is on.
public struct DialGains: Equatable, Sendable {
    public var stations: [Double]
    public var staticGain: Double
    public var isOn: Bool
}

/// The radio dial: needle travels 0...1. Below `offZone` the radio is off; each station is clean within
/// `full` of its position and fades with a raised cosine to 0 at `edge`; static fills what the stations leave.
/// Called from the UI thread (it allocates), never from the audio callback. Values are placeholders (docs/project-state.md, "Plan 9").
public enum Dial {
    public static let offZone = 0.06, full = 0.015, edge = 0.06, detent = 0.01, snap = 0.03

    public static func gains(needle: Double, stations: [StationRecipe]) -> DialGains {
        let n = clamped(needle, 0, 1)
        guard needle.isNaN == false, n >= offZone else {
            return DialGains(stations: Array(repeating: 0, count: stations.count), staticGain: 0, isOn: false)
        }
        let g = stations.map { stationGain(distance: abs(n - $0.dialPosition)) }
        return DialGains(stations: g, staticGain: 1 - (g.max() ?? 0), isOn: true)
    }

    /// Where the needle comes to rest on release: the nearest station within `snap`, else where it is.
    public static func snapped(_ needle: Double, stations: [StationRecipe]) -> Double {
        let n = clamped(needle, 0, 1)
        guard n >= offZone else { return n }
        let nearest = stations.min { abs(n - $0.dialPosition) < abs(n - $1.dialPosition) }
        if let s = nearest, abs(n - s.dialPosition) <= snap { return s.dialPosition }
        return n
    }

    /// What the lock screen calls it: the station whose gain is highest, when that gain is above
    /// `titleGain`; "DM static" between stations; nil when off.
    public static let titleGain = 0.5
    public static let staticTitle = "DM static"

    public static func nowPlayingTitle(needle: Double, stations: [StationRecipe]) -> String? {
        let g = gains(needle: needle, stations: stations)
        guard g.isOn else { return nil }
        guard let best = g.stations.indices.max(by: { g.stations[$0] < g.stations[$1] }),
              g.stations[best] > titleGain else { return staticTitle }
        return stations[best].title
    }

    /// The detent the needle is in; a haptic tick fires when this changes.
    public static func detentIndex(_ needle: Double) -> Int {
        Int((clamped(needle, 0, 1) / detent).rounded(.down))
    }

    private static func stationGain(distance d: Double) -> Double {
        if d <= full { return 1 }
        if d >= edge { return 0 }
        return 0.5 * (1 + cos(Double.pi * (d - full) / (edge - full)))
    }
}
