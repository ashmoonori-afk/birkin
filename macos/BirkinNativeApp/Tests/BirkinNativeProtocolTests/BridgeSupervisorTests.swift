import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Owned bridge supervisor")
struct BridgeSupervisorTests {
    @Test("user-launched bridge is attached but never spawned killed or restarted")
    func externalOwnershipBoundary() throws {
        var spawnCount = 0
        let supervisor = OwnedBridgeSupervisor(
            clock: { Date(timeIntervalSince1970: 1_000) },
            spawn: {
                spawnCount += 1
                return FakeBridgeProcess(pid: Int32(200 + spawnCount))
            }
        )

        supervisor.attachExisting(pid: 99)
        #expect(supervisor.state == .attachedExternal(pid: 99))
        #expect(!supervisor.startOwnedIfNeeded())
        supervisor.observeExit(pid: 99, status: 9)
        supervisor.shutdown()

        #expect(spawnCount == 0)
        #expect(supervisor.state == .stopped(reason: "app_shutdown"))
        #expect(supervisor.diagnostics.contains { $0.code == "external_bridge_untouched" })
    }

    @Test("owned crashed bridge restarts and shutdown terminates only current child")
    func ownedRestartAndShutdown() throws {
        var children: [FakeBridgeProcess] = []
        let supervisor = OwnedBridgeSupervisor(
            clock: { Date(timeIntervalSince1970: 2_000) },
            spawn: {
                let child = FakeBridgeProcess(pid: Int32(300 + children.count))
                children.append(child)
                return child
            }
        )

        #expect(supervisor.startOwnedIfNeeded())
        #expect(supervisor.state == .runningOwned(pid: 300))
        supervisor.observeExit(pid: 300, status: 9)
        #expect(supervisor.state == .runningOwned(pid: 301))
        #expect(children.count == 2)
        #expect(children[0].terminateCount == 0)

        supervisor.shutdown()
        #expect(children[1].terminateCount == 1)
        #expect(supervisor.state == .stopped(reason: "app_shutdown"))
    }
}

private final class FakeBridgeProcess: SupervisedBridgeProcess {
    let pid: Int32
    private(set) var terminateCount = 0

    init(pid: Int32) { self.pid = pid }

    func terminate() { terminateCount += 1 }
}
