import Testing
import Foundation

private func swiftFiles(under module: String) -> [URL] {
    let root = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources").appendingPathComponent(module)
    let e = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)
    return (e?.allObjects as? [URL] ?? []).filter { $0.pathExtension == "swift" }
}

private func importLines(_ url: URL) throws -> [String] {
    try String(contentsOf: url, encoding: .utf8)
        .split(separator: "\n", omittingEmptySubsequences: false)
        .map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { $0.hasPrefix("import ") || $0.contains(" import ") }
}

@Test func nightPlanImportsOnlyFoundation() throws {
    let files = swiftFiles(under: "NightPlan")
    #expect(!files.isEmpty)
    for f in files {
        for line in try importLines(f) {
            #expect(line.wholeMatch(of: /import (Foundation|Synchronization)/) != nil, "\(f.lastPathComponent): \(line)")
        }
    }
}

@Test func nightDSPImportsNoPlatformFrameworks() throws {
    let files = swiftFiles(under: "NightDSP")
    #expect(!files.isEmpty)
    for f in files {
        for line in try importLines(f) {
            #expect(line.firstMatch(of: /import (AVFoundation|UIKit|AppKit|SwiftUI)/) == nil, "\(f.lastPathComponent): \(line)")
        }
    }
}
