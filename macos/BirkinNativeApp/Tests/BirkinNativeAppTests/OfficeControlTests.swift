import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Office controls", .serialized)
struct OfficeControlTests {
    @MainActor
    @Test("the New control creates a document the canonical service accepts")
    func officeNewCreatesADocument() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-office-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(socketPath: socketPath, emit: { events.record($0) })
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }

        runtime.submit(ProductSurfaceControl.officeNew)
        try await withTimeout("office completed") {
            try await events.wait(for: "projection-event type=command.completed")
        }

        #expect(runtime.lastCommandError == nil, "office create was refused")
        try await withTimeout("office surface") {
            try await events.wait(for: "surface-applied name=office", occurrence: 2)
        }
        let surface = try #require(runtime.store.surface(named: "office"))
        guard case .array(let documents) = surface.payload["documents"] else {
            Issue.record("office surface has no documents array")
            return
        }
        #expect(documents.count == 1)
    }
}
