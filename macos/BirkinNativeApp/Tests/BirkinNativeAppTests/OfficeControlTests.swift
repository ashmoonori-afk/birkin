import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Office controls", .serialized)
struct OfficeControlTests {
    @MainActor
    @Test("the New control queues canonical Office approval")
    func officeNewQueuesCanonicalApproval() async throws {
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
        try await withTimeout("office approval request") {
            try await events.wait(for: "projection-event type=approval.requested")
        }
        try await withTimeout("office create request outcome") {
            try await events.wait(for: "projection-event type=command.completed")
        }

        #expect(runtime.lastCommandError == nil)
        let surface = try #require(runtime.store.surface(named: "office"))
        guard case .array(let documents) = surface.payload["documents"] else {
            Issue.record("office surface has no documents array")
            return
        }
        #expect(documents.isEmpty)
        #expect(events.recorded().filter {
            $0.hasPrefix("surface-applied name=office")
        }.count == 1)
    }
}
