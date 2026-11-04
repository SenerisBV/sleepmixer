import NightPlan
import NightRadio
import SwiftUI

/// Esoterica DM Radio: an old radio on the nightstand. One dark screen, one dial, one wheel.
@main
struct EsotericaApp: App {
    private let engine: RadioEngine
    private let audio: AudioSessionController
    /// The needle lives beside the engine, not in the view: a scene reconnect (unlocking the phone)
    /// redraws the dial where the radio actually is.
    @State private var dial = DialModel()

    init() {
        let engine = RadioEngine(bundles: Self.loadStations())
        self.engine = engine
        audio = AudioSessionController(engine: engine)
    }

    var body: some Scene {
        WindowGroup {
            DialView(engine: engine, audio: audio, model: dial)
                .preferredColorScheme(.dark)
                .statusBarHidden()
                .persistentSystemOverlays(.hidden)
        }
    }

    /// `Stations/<id>/station.json` in the app bundle (made by `make stations`). A station whose
    /// bundle is missing or unreadable still sits on the dial and plays its bed only.
    private static func loadStations() -> [String: StationBundle] {
        guard let root = Bundle.main.url(forResource: "Stations", withExtension: nil) else {
            NSLog("Esoterica: no Stations folder in the app; every station plays its bed only")
            return [:]
        }
        var bundles: [String: StationBundle] = [:]
        for recipe in StationRecipe.all {
            do {
                bundles[recipe.id] = try StationBundle.load(directory: root.appendingPathComponent(recipe.id))
            } catch {
                NSLog("Esoterica: station \(recipe.id) has no readable bundle (\(error)); bed only")
            }
        }
        return bundles
    }
}

/// Where the needle is, owned by the app for its whole life. Always starts in the off zone.
@Observable
final class DialModel {
    var needle = 0.0
}
