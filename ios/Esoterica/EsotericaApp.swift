import NightPlan
import NightRadio
import SwiftUI

/// Esoterica DM Radio: an old radio on the nightstand. One dark screen, one dial, one wheel.
@main
struct EsotericaApp: App {
    private let engine: RadioEngine
    private let audio: AudioSessionController

    init() {
        let engine = RadioEngine(bundles: Self.loadStations())
        self.engine = engine
        audio = AudioSessionController(engine: engine)
    }

    var body: some Scene {
        WindowGroup {
            DialView(engine: engine, audio: audio)
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
