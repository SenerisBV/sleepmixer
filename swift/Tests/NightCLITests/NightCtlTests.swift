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
