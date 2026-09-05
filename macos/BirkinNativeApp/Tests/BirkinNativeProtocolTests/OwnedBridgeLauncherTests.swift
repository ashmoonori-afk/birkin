import Darwin
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Frozen helper process ownership", .serialized)
struct OwnedBridgeLauncherTests {
    @Test("forged readiness never transfers signal authority to an announced PID")
    func forgedReadinessFailsClosed() throws {
        let root = try makeRoot()
        let script = root.appendingPathComponent("forged-helper")
        let sentinel = Process()
        sentinel.executableURL = URL(fileURLWithPath: "/bin/sleep")
        sentinel.arguments = ["300"]
        try sentinel.run()
        defer {
            if sentinel.isRunning { sentinel.terminate() }
            try? FileManager.default.removeItem(at: root)
        }
        try writeScript(
            """
            printf '{"event":"listening","pid":\(sentinel.processIdentifier),"transport":"uds","socket_path":"\(root.path)/bridge.sock"}\\n'
            /bin/sleep 300
            """,
            to: script
        )

        #expect(throws: OwnedBridgeLaunchError.readinessIdentityMismatch) {
            _ = try OwnedBridgeLauncher.launch(
                OwnedBridgeConfiguration(executable: script.path),
                onExit: { _, _ in }
            )
        }
        #expect(sentinel.isRunning)
        #expect(kill(sentinel.processIdentifier, 0) == 0)
        print("B1 SENTINEL pid=\(sentinel.processIdentifier) survived_forged_readiness=true")
    }

    @Test("the verified helper is drained for its complete lifetime")
    func postReadinessDiagnosticsAreDrained() throws {
        let root = try makeRoot()
        let script = root.appendingPathComponent("chatty-helper")
        try writeScript(
            """
            printf '{"event":"listening","pid":%s,"transport":"uds","socket_path":"\(root.path)/bridge.sock"}\\n' "$$"
            /usr/bin/head -c 131072 /dev/zero | /usr/bin/tr '\\0' x
            exit 0
            """,
            to: script
        )
        let exit = BridgeExitCapture()
        let launched = try OwnedBridgeLauncher.launch(
            OwnedBridgeConfiguration(executable: script.path),
            onExit: exit.record
        )
        defer {
            launched.process.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        #expect(exit.wait(seconds: 10))
        #expect(exit.pid == launched.process.pid)
        #expect(exit.status == 0)
        print("B2 DRAIN bytes=131072 helper_exited=true retained_bytes=0")
    }

    private func makeRoot() throws -> URL {
        let root = URL(fileURLWithPath: "/private/tmp/bk-launcher-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func writeScript(_ body: String, to url: URL) throws {
        try "#!/bin/bash\n\(body)\n".write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
    }
}

private final class BridgeExitCapture: @unchecked Sendable {
    private let lock = NSLock()
    private let signal = DispatchSemaphore(value: 0)
    private var recordedPID: Int32?
    private var recordedStatus: Int32?

    var pid: Int32? { lock.withLock { recordedPID } }
    var status: Int32? { lock.withLock { recordedStatus } }

    func record(pid: Int32, status: Int32) {
        lock.withLock {
            recordedPID = pid
            recordedStatus = status
        }
        signal.signal()
    }

    func wait(seconds: Int) -> Bool {
        signal.wait(timeout: .now() + .seconds(seconds)) == .success
    }
}
