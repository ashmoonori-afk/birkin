import BirkinNativeProtocol
import Foundation
import Testing

@testable import BirkinNativeShell

@Suite("Append-only Activity presentation")
@MainActor
struct ActivityPresentationTests {
    @Test("Hide read filters only the in-memory presentation")
    func hideReadIsInMemory() {
        let model = ActivityFilterModel()
        let items = [activity("receipt-1"), activity("warning-1")]

        model.markRead("receipt-1")
        #expect(model.visible(items).count == 2)
        model.hideRead = true
        #expect(model.visible(items).map { $0.string("id") } == ["warning-1"])
        model.hideRead = false
        #expect(model.visible(items).map { $0.string("id") } == ["receipt-1", "warning-1"])
    }

    @Test("Activity filter source has no persistence seam")
    func persistenceScan() throws {
        let source = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Sources/BirkinNativeShell/ActivityPresentation.swift")
        let text = try String(contentsOf: source, encoding: .utf8)
        for forbidden in ["UserDefaults", "AppStorage", "FileManager", "write(to:", "CoreData", "SwiftData"] {
            #expect(!text.contains(forbidden), "Activity hidden state persisted through \(forbidden)")
        }
    }

    private func activity(_ id: String) -> NativeJSONObject {
        ["id": .string(id), "summary": .string(id), "kind": .string("receipt")]
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
