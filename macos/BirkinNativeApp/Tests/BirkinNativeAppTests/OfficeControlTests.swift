import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Office controls", .serialized)
struct OfficeControlTests {
    @MainActor
    @Test("the New control requires canonical Office approval")
    func officeNewRequiresCanonicalApproval() async throws {
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
        try await withTimeout("office approval refusal") {
            try await events.wait(for: "command-error")
        }
        try await withTimeout("office failed outcome") {
            try await events.wait(for: "projection-event type=command.failed")
        }

        #expect(runtime.lastCommandError != nil)
        #expect(events.recorded().contains {
            $0.hasPrefix("command-error") && $0.contains("code=E_COMMAND_FAILED")
        })
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
