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

        @Argument(help: "chimes, waves, warmth, or voice (with --file)") public var scene: String
        @Option(help: "WAV file to play (required for voice, ignored otherwise).") public var file: String?
        @Option(help: "Length in seconds (0 to 3600).") public var seconds: Double = 60
        @Option(name: .customLong("at"), help: "Start second within the night.") public var at: Double = 0
        @Option public var seed: UInt64 = 1
        @Option public var distance: Double = 0
        @Option public var slowness: Double = 0
        @Option public var fragmentation: Double = 0
        @Option public var proportion: Double = 0
        @Option public var ring: Double = 0
        @Option public var softness: Double = 0
        @Option public var vibrato: Double = 0
        @Flag(name: .customLong("no-channel"), help: "Skip the AM channel.") public var noChannel = false
        @Option(name: .customLong("sample-rate")) public var sampleRate: Double = 44100
        @Option(help: "Output path (default ./<scene>-<seed>.wav).") public var out: String?
        @Flag(help: "Play the result with afplay.") public var play = false

        public init() {}

        public var sceneKind: SceneKind? { SceneKind(rawValue: scene) }
        public var isVoice: Bool { scene == "voice" }

        public func validate() throws {
            guard isVoice || sceneKind != nil else {
                throw ValidationError("unknown scene '\(scene)' (chimes, waves, warmth or voice).")
            }
            if !isVoice, file != nil {
                throw ValidationError("--file is only for voice (got scene '\(scene)').")
            }
            if isVoice {
                guard file != nil else { throw ValidationError("voice needs --file <path-to-wav>.") }
                for (name, v) in [("slowness", slowness), ("ring", ring), ("softness", softness), ("vibrato", vibrato)]
                where v != 0 {
                    throw ValidationError("--\(name) must be 0 for voice (got \(v)).")
                }
            }
            for (name, v) in [("distance", distance), ("slowness", slowness),
                              ("fragmentation", fragmentation), ("proportion", proportion),
                              ("ring", ring), ("softness", softness), ("vibrato", vibrato)] {
                guard v.isFinite, (0...1).contains(v) else {
                    throw ValidationError("--\(name) must be between 0 and 1 (got \(v)).")
                }
            }
            guard seconds.isFinite, seconds > 0, seconds <= 3600 else {
                throw ValidationError("--seconds must be greater than 0 and at most 3600 (got \(seconds)).")
            }
            guard at.isFinite, (0...86_400).contains(at) else {
                throw ValidationError("--at must be between 0 and 86400 (got \(at)).")
            }
            guard sampleRate.isFinite, (8000...192_000).contains(sampleRate) else {
                throw ValidationError("--sample-rate must be between 8000 and 192000 (got \(sampleRate)).")
            }
        }

        public func request() -> AuditionRequest {
            AuditionRequest(
                scene: sceneKind ?? .chimes, seconds: seconds, startSecond: at, seed: seed,
                warp: WarpDepth(distance: distance, slowness: slowness,
                                fragmentation: fragmentation, proportion: proportion,
                                ring: ring, softness: softness, vibrato: vibrato),
                channel: !noChannel, sampleRate: sampleRate)
        }

        /// `request()` plus the decoded voice clip: reads the WAV once, with a clear error.
        public func loadedRequest() throws -> AuditionRequest {
            var r = request()
            if isVoice, let file { r.voice = try VoiceClip.load(url: URL(fileURLWithPath: file)) }
            return r
        }

        public func run() throws {
            let path = out ?? "./\(scene)-\(seed).wav"
            let r = try loadedRequest()   // a bad WAV fails here, before any output
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
