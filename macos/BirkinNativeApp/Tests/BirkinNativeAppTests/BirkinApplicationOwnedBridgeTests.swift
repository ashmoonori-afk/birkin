import Darwin
import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged application owned bridge", .serialized)
struct BirkinApplicationOwnedBridgeTests {
    private static func configuration(root: URL) -> OwnedBridgeConfiguration {
        OwnedBridgeConfiguration(
            executable: AppHarness.repository
                .appendingPathComponent(".venv/bin/python3").path,
            leadingArguments: ["-m", "birkin"],
            serveOptions: [
                "--root", root.path,
                "--session-id", "owned-bridge-session",
            ]
        )
    }

    @MainActor
    @Test("the application starts, uses, restarts, and stops its own bridge")
    func ownsItsBridgeLifecycle() async throws {
        // A Unix socket path is platform bounded, so this root stays short.
        let root = URL(fileURLWithPath: "/private/tmp/bk-owned-\(UUID().uuidString)")
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: nil,
            ownedBridge: Self.configuration(root: root),
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("owned bridge start", seconds: 60) { await runtime.start() }

        #expect(events.contains("bridge-started kind=owned"))
        #expect(events.contains("connected transport=uds"), "log=\(events.recorded())")
        let firstPID = try #require(runtime.ownedBridgeProcessIdentifier)
        #expect(runtime.store.projection?.sessionID == "owned-bridge-session")

        _ = kill(firstPID, SIGKILL)
        try await withTimeout("owned bridge restart", seconds: 60) {
            try await events.wait(for: "bridge-restarted kind=owned")
        }
        let secondPID = try #require(runtime.ownedBridgeProcessIdentifier)
        #expect(secondPID != firstPID)

        try await withTimeout("reconnect after restart", seconds: 60) {
            try await events.wait(for: "replayed")
        }
        #expect(runtime.store.projection != nil)

        runtime.stop()
        #expect(runtime.ownedBridgeProcessIdentifier == nil)
        try await withTimeout("owned bridge exit", seconds: 30) {
            while kill(secondPID, 0) == 0 {
                try await Task.sleep(for: .milliseconds(20))
            }
        }
    }

    @MainActor
    @Test("an externally provided endpoint is used without starting a bridge")
    func externalEndpointIsNeverOwned() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-external-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            ownedBridge: Self.configuration(root: root.appendingPathComponent("owned")),
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("external start", seconds: 30) { await runtime.start() }

        #expect(events.contains("bridge-attached kind=external"))
        #expect(!events.contains("bridge-started kind=owned"))
        #expect(runtime.ownedBridgeProcessIdentifier == nil)
        #expect(harness.process.isRunning)
    }
}
