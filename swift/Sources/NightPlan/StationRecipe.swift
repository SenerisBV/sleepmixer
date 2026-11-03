import Foundation

/// One radio station: where it sits on the dial and the gains of its three beds.
/// `id` equals the station bundle directory name. Values are placeholders (docs/project-state.md, "Plan 9").
public struct StationRecipe: Sendable, Equatable {
    public let id: String, title: String, dialPosition: Double
    public let warmth: Double, chimes: Double, waves: Double

    public static let all: [StationRecipe] = [
        StationRecipe(id: "the-lantern-accords", title: "The Lantern Accords", dialPosition: 0.25,
                      warmth: 1.0, chimes: 0.25, waves: 0.2),
        StationRecipe(id: "backward-lesson-one", title: "Backward Lesson One", dialPosition: 0.55,
                      warmth: 0.3, chimes: 0.2, waves: 1.0),
        StationRecipe(id: "the-orchard-light", title: "The Orchard Light", dialPosition: 0.85,
                      warmth: 0.25, chimes: 1.0, waves: 0.3),
    ]
}
