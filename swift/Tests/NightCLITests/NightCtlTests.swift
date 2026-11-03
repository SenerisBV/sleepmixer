import ArgumentParser
import Foundation
import Testing
import NightDSP
import NightPlan
@testable import NightCLI

@Suite struct NightCtlTests {
    @Test func parsesARequest() throws {
        let a = try NightCtl.Audition.parse(
            ["chimes", "--seconds", "30", "--distance", "0.5", "--no-channel", "--seed", "9"])
        #expect(a.request() == AuditionRequest(
            scene: .chimes, seconds: 30, seed: 9, warp: WarpDepth(distance: 0.5), channel: false))
        let w = try NightCtl.Audition.parse(["warmth", "--seconds", "45", "--proportion", "1"])
        #expect(w.request() == AuditionRequest(scene: .warmth, seconds: 45, warp: WarpDepth(proportion: 1)))
    }

    @Test func parsesToneDials() throws {
        let a = try NightCtl.Audition.parse(
            ["chimes", "--ring", "0.5", "--softness", "1", "--vibrato", "0.25"])
        #expect(a.request().warp == WarpDepth(ring: 0.5, softness: 1, vibrato: 0.25))
    }

    @Test func rejectsBadInput() {
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["bells"]) }
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["chimes", "--distance", "1.5"]) }
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["chimes", "--seconds", "-1"]) }
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["chimes", "--at", "-3"]) }
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["chimes", "--seconds", "3601"]) }
    }

    /// Each bad value must be rejected by validate() (not by a parse-level "missing value"),
    /// and the message must name the field.
    @Test(arguments: [
        (["chimes", "--seconds=-1"], "--seconds"),
        (["chimes", "--seconds", "0"], "--seconds"),
        (["chimes", "--seconds=nan"], "--seconds"),
        (["chimes", "--at=-3"], "--at"),
        (["chimes", "--at=100000"], "--at"),
        (["chimes", "--distance=nan"], "--distance"),
        (["chimes", "--distance=1.5"], "--distance"),
        (["chimes", "--ring=1.5"], "--ring"),
        (["chimes", "--softness=-0.1"], "--softness"),
        (["chimes", "--vibrato=nan"], "--vibrato"),
    ])
    func validateNamesTheField(args: [String], field: String) {
        do {
            _ = try NightCtl.Audition.parse(args)
            Issue.record("\(args) parsed without error")
        } catch {
            let message = NightCtl.Audition.message(for: error)
            #expect(message.contains("must be"), "\(args): \(message)")
            #expect(message.contains(field), "\(args): \(message)")
        }
    }

    @Test func badInputWritesNothing() throws {
        let tmp = NSTemporaryDirectory() + "nightctl-bad-\(UUID().uuidString).wav"
        #expect(throws: (any Error).self) {
            try NightCtl.parseAsRoot(["audition", "chimes", "--distance", "2", "--out", tmp])
        }
        #expect(!FileManager.default.fileExists(atPath: tmp))
    }
}

@Suite struct NightCtlVoiceTests {
    func tmp(_ name: String) -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("nightctl-\(UUID().uuidString)-\(name)")
    }

    @Test func parsesVoice() throws {
        let a = try NightCtl.Audition.parse(["voice", "--file", "/x/p01.wav", "--distance", "0.5"])
        #expect(a.isVoice && a.file == "/x/p01.wav")
        #expect(a.request().warp == WarpDepth(distance: 0.5))
        #expect(a.request().voice == nil)   // the clip is attached by loadedRequest(), which reads the file
        #expect(try NightCtl.Audition.parse(["chimes"]).request().voice == nil)
    }

    @Test func loadedRequestCarriesTheDecodedClip() throws {
        let src = tmp("clip.wav")
        try WAVWriter.write([0.1, 0.2, 0.3], sampleRate: 22050, to: src)
        let a = try NightCtl.Audition.parse(["voice", "--file", src.path])
        #expect(try a.loadedRequest().voice == VoiceClip(samples: [0.1, 0.2, 0.3], sampleRate: 22050))
    }

    @Test func fileIsOnlyForVoice() {
        do {
            _ = try NightCtl.Audition.parse(["chimes", "--file", "x.wav"])
            Issue.record("--file accepted for a scene")
        } catch {
            #expect(NightCtl.Audition.message(for: error).contains("--file is only for voice"))
        }
    }

    @Test func unknownSceneNamesItself() {
        do {
            _ = try NightCtl.Audition.parse(["bells"])
            Issue.record("unknown scene accepted")
        } catch {
            #expect(NightCtl.Audition.message(for: error).contains("unknown scene 'bells'"))
        }
    }

    @Test func voiceNeedsAFile() {
        #expect(throws: (any Error).self) { try NightCtl.Audition.parse(["voice"]) }
    }

    @Test(arguments: ["slowness", "ring", "softness", "vibrato"])
    func voiceRejectsToneDials(dial: String) {
        do {
            _ = try NightCtl.Audition.parse(["voice", "--file", "x.wav", "--\(dial)", "0.5"])
            Issue.record("--\(dial) accepted for voice")
        } catch {
            let message = NightCtl.Audition.message(for: error)
            #expect(message.contains("must be 0 for voice"), "\(message)")
            #expect(message.contains(dial), "\(message)")
        }
    }

    @Test func unsupportedWAVGivesAClearErrorAndNoOutput() throws {
        let bad = tmp("bad.wav")
        try Data("RIFF....WAVEfmt ".utf8).write(to: bad)
        let out = tmp("out.wav")
        var cmd = try NightCtl.parseAsRoot(["audition", "voice", "--file", bad.path, "--out", out.path])
        do {
            try cmd.run()
            Issue.record("run succeeded on a bad WAV")
        } catch {
            #expect(!NightCtl.message(for: error).isEmpty)
        }
        #expect(!FileManager.default.fileExists(atPath: out.path))
    }

    @Test func rendersAVoiceFile() throws {
        let src = tmp("in.wav"), out = tmp("out.wav")
        let tone = (0..<44100).map { Float(0.3 * sin(2 * Double.pi * 220 * Double($0) / 44100)) }
        try WAVWriter.write(tone, sampleRate: 44100, to: src)
        var cmd = try NightCtl.parseAsRoot(["audition", "voice", "--file", src.path, "--seconds", "1", "--out", out.path])
        try cmd.run()
        let back = try WAVReader.read(url: out)
        #expect(back.samples.count == 44100)
        #expect(back.samples.allSatisfy { $0.isFinite })
    }
}
