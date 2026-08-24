import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@MainActor
private func importSession(of runtime: BirkinApplicationRuntime) -> NativeReadySession? {
    switch runtime.connectionState {
    case .ready(let value), .fallback(.ready(let value)): value
    default: nil
    }
}

@Suite("Packaged application jailed import", .serialized)
struct BirkinApplicationImportTests {
    @MainActor
    @Test("a jailed import receipt produces a composer reference chip")
    func importReceiptProducesComposerReference() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-import-\(UUID().uuidString)")
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
        let ready = try #require(importSession(of: runtime))
        let dropped = root.appendingPathComponent("dropped-note.txt")
        try Data("imported through the app runtime".utf8).write(to: dropped)

        #expect(runtime.jailedDrop.accept(
            urls: [dropped],
            availability: MutationAvailability(state: runtime.connectionState, now: Date()),
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            session: ready,
            submit: { runtime.submit($0) }
        ))
        #expect(runtime.jailedDrop.state == .importing(displayName: "dropped-note.txt"))

        try await withTimeout("import completed") {
            try await events.wait(for: "projection-event type=command.completed")
        }

        let reference = try #require(runtime.jailedDrop.reference)
        #expect(runtime.jailedDrop.state == .imported)
        #expect(reference.displayName == "dropped-note.txt")
        #expect(reference.sha256.count == 64)
        #expect(reference.composerToken == "[[workspace-import:\(reference.importID)]]")
        #expect(runtime.lastCommandError == nil)
    }

    @MainActor
    @Test("a refused import ends in a bounded visible failure")
    func refusedImportBecomesVisibleFailure() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-app-import-fail-\(UUID().uuidString)")
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
        let ready = try #require(importSession(of: runtime))
        let missing = root.appendingPathComponent("never-created.txt")

        #expect(runtime.jailedDrop.accept(
            urls: [missing],
            availability: MutationAvailability(state: runtime.connectionState, now: Date()),
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            session: ready,
            submit: { runtime.submit($0) }
        ))

        try await withTimeout("import refusal") {
            try await events.wait(for: "command-error")
        }

        #expect(runtime.jailedDrop.reference == nil)
        guard case .refused(let reason) = runtime.jailedDrop.state else {
            Issue.record("import stayed in \(runtime.jailedDrop.state)")
            return
        }
        #expect(!reason.isEmpty)
        #expect(reason.count <= 300)
    }
}
