import Foundation

/// The "channel" a scene is heard through: band limits, noise floor, fade and squash.
/// All values are placeholders pending listening (see docs/project-state.md).
public struct ChannelSettings: Equatable, Sendable {
    public var lowCornerHz: Double { didSet { lowCornerHz = clamped(lowCornerHz, 40, 1000); enforceOctave() } }
    public var highCornerHz: Double { didSet { highCornerHz = clamped(highCornerHz, 800, 8000); enforceOctave() } }
    public var hissLevelDB: Double { didSet { hissLevelDB = clamped(hissLevelDB, -96, -20) } }
    public var crackleLevelDB: Double { didSet { crackleLevelDB = clamped(crackleLevelDB, -96, -20) } }
    public var fadeDepth: Double { didSet { fadeDepth = clamped(fadeDepth, 0, 1) } }
    public var fadeRateHz: Double { didSet { fadeRateHz = clamped(fadeRateHz, 0.005, 1) } }
    public var squash: Double { didSet { squash = clamped(squash, 0, 1) } }

    public init(lowCornerHz: Double, highCornerHz: Double, hissLevelDB: Double, crackleLevelDB: Double,
                fadeDepth: Double, fadeRateHz: Double, squash: Double) {
        self.lowCornerHz = clamped(lowCornerHz, 40, 1000)
        self.highCornerHz = clamped(highCornerHz, 800, 8000)
        self.hissLevelDB = clamped(hissLevelDB, -96, -20)
        self.crackleLevelDB = clamped(crackleLevelDB, -96, -20)
        self.fadeDepth = clamped(fadeDepth, 0, 1)
        self.fadeRateHz = clamped(fadeRateHz, 0.005, 1)
        self.squash = clamped(squash, 0, 1)
        enforceOctave()
    }

    /// The band keeps at least an octave: raise the high corner (low max 1000 so 2000 always fits).
    private mutating func enforceOctave() {
        if highCornerHz < lowCornerHz * 2 { highCornerHz = lowCornerHz * 2 }
    }

    public static let early = ChannelSettings(
        lowCornerHz: 180, highCornerHz: 4500, hissLevelDB: -48, crackleLevelDB: -54,
        fadeDepth: 0.25, fadeRateHz: 0.05, squash: 0.5)
}
