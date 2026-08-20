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

    @Test("five crashes in sixty seconds stop restart and expose bounded diagnostics")
    func fiveInSixtyCeiling() {
        var now = Date(timeIntervalSince1970: 5_000)
        var spawnCount = 0
        let supervisor = OwnedBridgeSupervisor(
            diagnosticCapacity: 4,
            clock: { now },
            spawn: {
                defer { spawnCount += 1 }
                return FakeBridgeProcess(pid: Int32(400 + spawnCount))
            }
        )
        #expect(supervisor.startOwnedIfNeeded())

        for offset in 0..<5 {
            now = Date(timeIntervalSince1970: 5_000 + Double(offset * 10))
            supervisor.observeExit(pid: Int32(400 + offset), status: 9)
        }

        #expect(spawnCount == 5)
        #expect(supervisor.state == .stopped(reason: "crash_loop"))
        #expect(supervisor.diagnostics.count == 4)
        #expect(supervisor.diagnostics.last?.code == "restart_ceiling_reached")
        #expect(supervisor.diagnostics.allSatisfy { $0.message.count <= 160 })
    }

    @Test("crashes outside sixty second window do not trip ceiling")
    func crashWindowExpires() {
        var now = Date(timeIntervalSince1970: 8_000)
        var spawnCount = 0
        let supervisor = OwnedBridgeSupervisor(
            clock: { now },
            spawn: {
                defer { spawnCount += 1 }
                return FakeBridgeProcess(pid: Int32(500 + spawnCount))
            }
        )
        #expect(supervisor.startOwnedIfNeeded())
        for offset in 0..<6 {
            now = Date(timeIntervalSince1970: 8_000 + Double(offset * 61))
            supervisor.observeExit(pid: Int32(500 + offset), status: 9)
        }
        #expect(spawnCount == 7)
        #expect(supervisor.state == .runningOwned(pid: 506))
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
