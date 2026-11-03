import Foundation

/// A station's recording on disk: `<directory>/station.json` plus one WAV per segment.
/// `station.json` is `{"id", "title", "segments": [{"file": "s01.wav", "seconds": 41.2}, ...]}`.
/// Only the manifest is read here; the segment files are loaded on the render thread as they come up,
/// and a missing or unreadable file is silence for that segment.
public struct StationBundle: Sendable, Equatable {
    public let id: String
    public let title: String
    public let segmentSeconds: [Double]
    public let segmentURLs: [URL]

    public init(id: String, title: String, segmentSeconds: [Double], segmentURLs: [URL]) {
        precondition(segmentSeconds.count == segmentURLs.count, "one URL per segment")
        self.id = id
        self.title = title
        self.segmentSeconds = segmentSeconds
        self.segmentURLs = segmentURLs
    }

    private struct Manifest: Decodable {
        struct Segment: Decodable { let file: String; let seconds: Double }
        let id: String
        let title: String
        let segments: [Segment]
    }

    public static func load(directory: URL) throws -> StationBundle {
        let data = try Data(contentsOf: directory.appendingPathComponent("station.json"))
        let m = try JSONDecoder().decode(Manifest.self, from: data)
        return StationBundle(id: m.id, title: m.title,
                             segmentSeconds: m.segments.map(\.seconds),
                             segmentURLs: m.segments.map { directory.appendingPathComponent($0.file) })
    }
}
