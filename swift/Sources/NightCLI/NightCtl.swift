import ArgumentParser
import Foundation
import NightDSP
import NightPlan

extension SceneKind: ExpressibleByArgument {}

public struct NightCtl: ParsableCommand {
    public static let configuration = CommandConfiguration(
        commandName: "nightctl",
        abstract: "Audition a scene through the night factory.",
        subcommands: [Scenes.self, Audition.self])

    public init() {}

    public struct Scenes: ParsableCommand {
        public static let configuration = CommandConfiguration(abstract: "List the scenes.")
        public init() {}
        public func run() throws {
            for k in SceneKind.allCases { print(k.rawValue) }
        }
    }

    public struct Audition: ParsableCommand {
        public static let configuration = CommandConfiguration(abstract: "Render a scene to a WAV file.")

        @Argument(help: "chimes or waves") public var scene: SceneKind
        @Option(help: "Length in seconds (0 to 3600).") public var seconds: Double = 60
        @Option(name: .customLong("at"), help: "Start second within the night.") public var at: Double = 0
        @Option public var seed: UInt64 = 1
        @Option public var distance: Double = 0
        @Option public var slowness: Double = 0
        @Option public var fragmentation: Double = 0
        @Option public var proportion: Double = 0
        @Flag(name: .customLong("no-channel"), help: "Skip the AM channel.") public var noChannel = false
        @Option(name: .customLong("sample-rate")) public var sampleRate: Double = 44100
        @Option(help: "Output path (default ./<scene>-<seed>.wav).") public var out: String?
        @Flag(help: "Play the result with afplay.") public var play = false

        public init() {}

        public func validate() throws {
            for (name, v) in [("distance", distance), ("slowness", slowness),
                              ("fragmentation", fragmentation), ("proportion", proportion)] {
                guard v.isFinite, (0...1).contains(v) else {
                    throw ValidationError("--\(name) must be between 0 and 1 (got \(v)).")
                }
            }
            guard seconds.isFinite, seconds > 0, seconds <= 3600 else {
                throw ValidationError("--seconds must be greater than 0 and at most 3600 (got \(seconds)).")
            }
            guard at.isFinite, at >= 0 else {
                throw ValidationError("--at must be 0 or more (got \(at)).")
            }
            guard sampleRate.isFinite, (8000...192_000).contains(sampleRate) else {
                throw ValidationError("--sample-rate must be between 8000 and 192000 (got \(sampleRate)).")
            }
        }

        public func request() -> AuditionRequest {
            AuditionRequest(
                scene: scene, seconds: seconds, startSecond: at, seed: seed,
                warp: WarpDepth(distance: distance, slowness: slowness,
                                fragmentation: fragmentation, proportion: proportion),
                channel: !noChannel, sampleRate: sampleRate)
        }

        public func run() throws {
            let path = out ?? "./\(scene.rawValue)-\(seed).wav"
            let r = request()
            let samples = NightFactory.audition(r)
            try WAVWriter.write(samples, sampleRate: Int(r.sampleRate), to: URL(fileURLWithPath: path))
            let rms = Analysis.rmsDB(samples[...])
            let peak = Analysis.peakDB(samples)
            let centroid = Analysis.centroidHz(samples, sampleRate: r.sampleRate)
            print("\(path)  rms \(String(format: "%.1f", rms)) dB  peak \(String(format: "%.1f", peak)) dB  centroid \(String(format: "%.0f", centroid)) Hz")
            if play {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
                p.arguments = [path]
                try p.run()
                p.waitUntilExit()
            }
        }
    }
}
