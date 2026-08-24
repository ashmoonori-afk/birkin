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

    @Test("typed Activity items expose lifecycle, receipts, failures, and details")
    func typedPresentations() {
        let tool = ActivityPresentation([
            "id": .string("tool-1"), "kind": .string("activity"),
            "summary": .string("Run grep"), "ui_state": .string("running"),
            "status": .string("started"), "target": .string("Sources"),
        ])
        let receipt = ActivityPresentation([
            "id": .string("receipt-1"), "kind": .string("receipt"),
            "summary": .string("Command completed"), "ui_state": .string("succeeded"),
            "receipt_ref": .string("receipt:1"),
        ])
        let failure = ActivityPresentation([
            "id": .string("failure-1"), "kind": .string("failure"),
            "summary": .string("Command failed"), "ui_state": .string("failed"),
            "code": .string("E_PROVIDER"), "message": .string("Unavailable"),
        ])

        #expect(tool?.kind == .tool)
        #expect(tool?.isExpandable == true)
        #expect(tool?.details.first?.label == "Target")
        #expect(receipt?.kind == .receipt)
        #expect(receipt?.receiptReference == "receipt:1")
        #expect(failure?.kind == .failure)
        #expect(failure?.failure?.code == "E_PROVIDER")
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
