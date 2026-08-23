import Foundation
import Testing

@testable import BirkinNativeApp

@Suite("Packaged application Browser failures", .serialized)
struct BirkinApplicationBrowserFailureIntegrationTests {
    @MainActor
    @Test("Browser command failure ends without waiting for a receipt")
    func commandFailureEndsImmediately() async throws {
        let root = URL(
            fileURLWithPath: "/private/tmp/bk-browser-failure-\(UUID().uuidString)"
        )
        let harness = try AppHarness.launch(root: root, environment: [
            "BIRKIN_HOME": root.appendingPathComponent("home").path,
            "BIRKIN_BROWSER_FORCE_UNAVAILABLE": "1",
        ])
        let socketPath = try #require(harness.socketPath)
        let runtimeEvents = RuntimeEventRecorder()
        let journeyEvents = JourneyEventLog()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            emit: {
                runtimeEvents.record($0)
                journeyEvents.record($0)
            }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start", seconds: 60) {
            await runtime.start()
        }
        try await withTimeout("initial Browser surface") {
            try await runtimeEvents.wait(for: "surface-applied name=browser_aside")
        }
        let browserURL = try #require(URL(string: "http://127.0.0.1:1/"))
        let runner = PackagedJourneyRunner(
            configuration: PackagedJourneyConfiguration(
                evidenceRoot: root.appendingPathComponent("evidence"),
                workspaceRoot: root,
                browserURL: browserURL
            ),
            runtime: runtime,
            events: journeyEvents
        )

        do {
            try await withTimeout("Browser command failure", seconds: 5) {
                try await runner.driveBrowser()
            }
            Issue.record("Browser command unexpectedly succeeded")
        } catch JourneyError.refused {
        } catch {
            Issue.record("unexpected Browser failure: \(error)")
        }
    }
}
