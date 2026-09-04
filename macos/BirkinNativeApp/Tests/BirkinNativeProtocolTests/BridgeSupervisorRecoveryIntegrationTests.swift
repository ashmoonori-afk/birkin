import Darwin
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Real owned bridge recovery")
struct BridgeSupervisorRecoveryIntegrationTests {
    @Test("authenticated relaunch reclaims the same live helper instance exactly once")
    func authenticatedRelaunchClaim() async throws {
        let repository = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
        let root = URL(fileURLWithPath: "/private/tmp/bk-reclaim-\(UUID().uuidString)")
        let configuration = OwnedBridgeConfiguration(
            executable: repository.appendingPathComponent(".venv/bin/python3").path,
            leadingArguments: ["-m", "birkin"],
            serveOptions: ["--root", root.path, "--session-id", "reclaim-session"]
        )
        let exit = DispatchSemaphore(value: 0)
        let first = try OwnedBridgeLauncher.launch(configuration) { _, _ in exit.signal() }
        defer { first.process.terminate() }

        let reclaimed = try #require(try OwnedBridgeLauncher.reclaim(configuration))
        #expect(reclaimed.process.pid == first.process.pid)
        #expect(reclaimed.endpointPath == first.endpointPath)
        let transcript = try await NativeTransportActor().connectUDS(
            socketPath: reclaimed.endpointPath, hello: integrationHello
        )
        #expect(transcript.session.instanceID == reclaimed.instanceID)
        reclaimed.process.terminate()
        #expect(kill(first.process.pid, 0) == 0)
        print(
            "B3 RELAUNCH pid=\(first.process.pid) instance=\(transcript.session.instanceID)"
                + " reclaimed=true spawned=1 pid_signalled=false"
        )
        first.process.terminate()
        let exited = await Task.detached { waitForBridgeExit(exit) }.value
        #expect(exited)
        try FileManager.default.removeItem(at: root)
    }

    @Test("owned crash restarts and app relaunch reattaches without duplicate sessions")
    func bothDirectionRestart() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/birkin-supervisor-\(UUID().uuidString)")
        var harnesses: [HarnessReadiness] = []
        let supervisor = OwnedBridgeSupervisor(
            spawn: {
                let harness = try HarnessReadiness.launch(
                    transport: "uds",
                    options: HarnessLaunchOptions(root: root)
                )
                harnesses.append(harness)
                return FoundationBridgeProcess(process: harness.process)
            }
        )
        defer { try? FileManager.default.removeItem(at: root) }

        try #require(supervisor.startOwnedIfNeeded())
        let firstHarness = try #require(harnesses.first)
        let crashedPID = firstHarness.process.processIdentifier
        #expect(kill(crashedPID, SIGKILL) == 0)
        let crashReceipt = try firstHarness.finish(removeRoot: false)
        #expect(firstHarness.process.terminationReason == .uncaughtSignal)
        supervisor.observeExit(pid: crashedPID, status: firstHarness.process.terminationStatus)

        let restartedHarness = try #require(harnesses.count == 2 ? harnesses[1] : nil)
        let restartedPID = restartedHarness.process.processIdentifier
        #expect(restartedPID != crashedPID)
        #expect(supervisor.state == .runningOwned(pid: restartedPID))
        let socketPath = try #require(restartedHarness.record["socket_path"] as? String)
        // A relaunched app discovers the live helper but never adopts process
        // ownership. It reconnects to the canonical session rather than creating one.
        var relaunchSpawnCount = 0
        let relaunched = OwnedBridgeSupervisor(
            spawn: {
                relaunchSpawnCount += 1
                throw HarnessError.malformedReadiness
            }
        )
        relaunched.attachExisting(pid: restartedPID)
        #expect(!relaunched.startOwnedIfNeeded())
        let transport = NativeTransportActor()
        let replayed = try await transport.connectUDS(
            socketPath: socketPath, hello: integrationHello
        )
        #expect(replayed.session.instanceID == "swift-integration-instance")
        #expect(relaunchSpawnCount == 0)

        let cleanupReceipt = try restartedHarness.finish(removeRoot: false)
        relaunched.shutdown()
        supervisor.shutdown()
        let sessions = try FileManager.default.contentsOfDirectory(
            at: root.appendingPathComponent("workspace"),
            includingPropertiesForKeys: nil
        )
        #expect(sessions.map(\.lastPathComponent) == ["session-1"])
        #expect(!FileManager.default.fileExists(
            atPath: root.appendingPathComponent("bridge.sock").path
        ))

        print("SUPERVISOR CRASH pid=\(crashedPID) signal=SIGKILL receipt=\(crashReceipt)")
        print("SUPERVISOR RESTART old=\(crashedPID) new=\(restartedPID) state=replayed")
        print("SUPERVISOR RELAUNCH attached_external=true spawned=\(relaunchSpawnCount) sessions=1")
        print("SUPERVISOR CLEANUP \(cleanupReceipt) socket_removed=true root_removed=deferred")
    }
}

private func waitForBridgeExit(_ semaphore: DispatchSemaphore) -> Bool {
    semaphore.wait(timeout: .now() + 10) == .success
}
