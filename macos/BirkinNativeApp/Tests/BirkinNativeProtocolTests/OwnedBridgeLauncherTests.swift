import Darwin
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Frozen helper process ownership")
struct OwnedBridgeLauncherTests {
    @Test("announced server child is the supervised process")
    func announcedChildOwnership() throws {
        // Given a one-file-style launcher parent that announces a serving child.
        let root = URL(fileURLWithPath: "/private/tmp/bk-launcher-\(UUID().uuidString)")
        let script = root.appendingPathComponent("frozen-helper")
        let childRecord = root.appendingPathComponent("child.pid")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try """
        #!/bin/bash
        /bin/sleep 300 &
        child=$!
        printf '%s' "$child" > '\(childRecord.path)'
        printf '{"event":"listening","pid":%s,"socket_path":"\(root.path)/bridge.sock"}\\n' "$child"
        wait "$child" 2>/dev/null || true
        """.write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755], ofItemAtPath: script.path
        )
        let exit = BridgeExitCapture()
        let launched = try OwnedBridgeLauncher.launch(
            OwnedBridgeConfiguration(executable: script.path),
            onExit: exit.record
        )
        let childPID = try #require(Int32(
            String(contentsOf: childRecord, encoding: .utf8)
        ))
        defer {
            _ = kill(childPID, SIGKILL)
            launched.process.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        // When app ownership terminates the announced server.
        #expect(launched.process.pid == childPID)
        launched.process.terminate()

        // Then exit attribution and termination both target that child, not its parent.
        #expect(exit.wait(seconds: 10))
        #expect(exit.pid == childPID)
        #expect(kill(childPID, 0) == -1)
    }
}

private final class BridgeExitCapture: @unchecked Sendable {
    private let lock = NSLock()
    private let signal = DispatchSemaphore(value: 0)
    private var recordedPID: Int32?

    var pid: Int32? { lock.withLock { recordedPID } }

    func record(pid: Int32, status _: Int32) {
        lock.withLock { recordedPID = pid }
        signal.signal()
    }

    func wait(seconds: Int) -> Bool {
        signal.wait(timeout: .now() + .seconds(seconds)) == .success
    }
}
