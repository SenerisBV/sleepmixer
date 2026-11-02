import Foundation

/// How far a scene is bent away from its plain self. Every field lives in 0...1; NaN becomes 0.
public struct WarpDepth: Equatable, Sendable {
    public var distance: Double { didSet { distance = clamped(distance, 0, 1) } }
    public var slowness: Double { didSet { slowness = clamped(slowness, 0, 1) } }
    public var fragmentation: Double { didSet { fragmentation = clamped(fragmentation, 0, 1) } }
    public var proportion: Double { didSet { proportion = clamped(proportion, 0, 1) } }

    public init(distance: Double = 0, slowness: Double = 0, fragmentation: Double = 0, proportion: Double = 0) {
        self.distance = clamped(distance, 0, 1)
        self.slowness = clamped(slowness, 0, 1)
        self.fragmentation = clamped(fragmentation, 0, 1)
        self.proportion = clamped(proportion, 0, 1)
    }

    public static let plain = WarpDepth()
}
