import Darwin
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Real owned bridge recovery")
struct BridgeSupervisorRecoveryIntegrationTests {
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

        #expect(supervisor.startOwnedIfNeeded())
        let crashedPID = harnesses[0].process.processIdentifier
        #expect(kill(crashedPID, SIGKILL) == 0)
        let crashReceipt = try harnesses[0].finish(removeRoot: false)
        #expect(harnesses[0].process.terminationReason == .uncaughtSignal)
        supervisor.observeExit(pid: crashedPID, status: harnesses[0].process.terminationStatus)

        #expect(harnesses.count == 2)
        let restartedPID = harnesses[1].process.processIdentifier
        #expect(restartedPID != crashedPID)
        #expect(supervisor.state == .runningOwned(pid: restartedPID))
        let socketPath = try #require(harnesses[1].record["socket_path"] as? String)
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

        let cleanupReceipt = try harnesses[1].finish(removeRoot: false)
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
