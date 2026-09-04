import Darwin
import Foundation
import Testing

@testable import BirkinNativeProtocol

@Suite("Real loopback fallback transport")
struct NativeLoopbackTransportIntegrationTests {
    @Test("cancellation closes a subscription blocked before its snapshot")
    func cancellationClosesBlockedSubscription() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-cancel-\(UUID().uuidString)")
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        let socketPath = root.appendingPathComponent("bridge.sock").path
        let server = try BlockingSubscriptionServer(path: socketPath)
        let transport = NativeTransportActor()
        defer {
            server.close()
            try? FileManager.default.removeItem(at: root)
        }

        let acquisition = Task<Result<NativeProjectionSubscription, any Error>, Never> {
            do {
                return .success(try await transport.openProjectionSubscriptionUDS(
                    socketPath: socketPath,
                    hello: integrationHello,
                    replaying: false
                ))
            } catch {
                return .failure(error)
            }
        }
        #expect(await server.waitUntilSubscribed())

        acquisition.cancel()

        let closedByClient = await server.waitUntilClosed()
        if !closedByClient {
            server.close()
        }
        let result = await acquisition.value
        #expect(closedByClient)
        #expect(throws: CancellationError.self) {
            try result.get()
        }
        #expect(await transport.state == .disconnected)
        #expect(!FileManager.default.fileExists(atPath: socketPath))
    }

    @Test("UDS authentication failure is terminal and never opens loopback")
    func authenticationFailureDoesNotFallback() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-auth-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let socketPath = root.appendingPathComponent("bridge.sock").path
        let refusing = try RefusingUDSServer(
            path: socketPath,
            envelope: NativeEnvelope(
                kind: .error, id: "auth-refusal",
                body: [
                    "code": .string("E_PEER_UID_MISMATCH"),
                    "message": .string("same-user authentication failed"),
                    "retryable": .bool(false),
                ]
            )
        )
        let loopback = try HarnessReadiness.launch(transport: "loopback")
        defer {
            refusing.close()
            if loopback.process.isRunning { loopback.process.terminate() }
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: loopback.root)
        }
        let discoveryPath = try #require(loopback.record["discovery_path"] as? String)
        let transport = NativeTransportActor()

        do {
            _ = try await transport.connectWithFallback(
                udsSocketPath: socketPath,
                discoveryPath: discoveryPath,
                hello: integrationHello
            )
            Issue.record("authentication failure unexpectedly downgraded")
        } catch let error as NativeTransportError {
            #expect(error.reason.contains("correlated ready"))
        }
        #expect(loopback.process.isRunning)
        #expect(await refusing.finished())
        print("B5 AUTH uds=E_PEER_UID_MISMATCH loopback_attempted=false")
    }

    @Test("UDS version failure is terminal and never downgraded to loopback")
    func versionFailureDoesNotFallback() async throws {
        let uds = try HarnessReadiness.launch(
            transport: "uds",
            options: HarnessLaunchOptions(serverVersion: "99.0.0")
        )
        let loopback = try HarnessReadiness.launch(transport: "loopback")
        defer {
            if uds.process.isRunning { uds.process.terminate() }
            if loopback.process.isRunning { loopback.process.terminate() }
            try? FileManager.default.removeItem(at: uds.root)
            try? FileManager.default.removeItem(at: loopback.root)
        }
        let socketPath = try #require(uds.record["socket_path"] as? String)
        let discoveryPath = try #require(loopback.record["discovery_path"] as? String)
        let transport = NativeTransportActor()

        do {
            _ = try await transport.connectWithFallback(
                udsSocketPath: socketPath,
                discoveryPath: discoveryPath,
                hello: integrationHello
            )
            Issue.record("version failure unexpectedly downgraded to loopback")
        } catch let error as NativeProductVersionError {
            #expect(error.actual == "99.0.0")
        }
        guard case .failed = await transport.state else {
            Issue.record("version failure did not remain terminal")
            return
        }
        #expect(loopback.process.isRunning)
        print("B5 ANTI-DOWNGRADE uds=version_failure loopback_attempted=false")
    }

    @Test("missing UDS falls back through discovery and authenticates")
    func authenticatedFallback() async throws {
        let harness = try HarnessReadiness.launch(transport: "loopback")
        guard let discoveryPath = harness.record["discovery_path"] as? String else {
            throw HarnessError.malformedReadiness
        }
        let transport = NativeTransportActor()

        let transcript = try await transport.connectWithFallback(
            udsSocketPath: harness.root.appendingPathComponent("unavailable.sock").path,
            discoveryPath: discoveryPath,
            hello: integrationHello
        )

        #expect(transcript.hello.kind == .hello)
        #expect(transcript.ready.kind == .ready)
        #expect(transcript.transport == .loopback)
        #expect(await transport.state == .fallback(.ready(transcript.session)))
        #expect(transcript.ready.inReplyTo == transcript.hello.id)
        print(
            "FALLBACK TRANSCRIPT hello=\(transcript.hello.id) "
                + "ready=\(transcript.ready.id) transport=loopback state=fallback.ready"
        )
        print("FALLBACK CLEANUP \(try harness.finish()) root_removed=true")
    }
}

private final class BlockingSubscriptionServer: @unchecked Sendable {
    private let listener: Int32
    private let path: String
    private let subscribed = DispatchSemaphore(value: 0)
    private let finished = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var connection: Int32 = -1
    private var clientClosed = false

    init(path: String) throws {
        self.path = path
        listener = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard listener >= 0 else {
            throw NativeTransportError("test socket failed")
        }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { bytes in
            bytes.copyBytes(from: Array(path.utf8) + [0])
        }
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(
                    listener,
                    $0,
                    socklen_t(MemoryLayout<sockaddr_un>.size)
                )
            }
        }
        guard bound == 0, Darwin.listen(listener, 1) == 0 else {
            _ = Darwin.close(listener)
            throw NativeTransportError("test bind failed")
        }

        Thread.detachNewThread { [self] in
            defer {
                lock.withLock {
                    if connection >= 0 {
                        _ = Darwin.close(connection)
                        connection = -1
                    }
                }
                _ = Darwin.close(listener)
                _ = unlink(path)
                finished.signal()
            }
            let accepted = Darwin.accept(listener, nil, nil)
            guard accepted >= 0 else { return }
            lock.withLock { connection = accepted }
            do {
                let hello = try receiveEnvelope(accepted)
                let ready = NativeEnvelope(
                    kind: .ready,
                    id: "cancel-ready",
                    inReplyTo: hello.id,
                    body: [
                        "transport": .string("uds"),
                        "instance_id": .string("cancel-instance"),
                        "server_version": .string(BirkinVersion.packageVersion),
                        "session_id": .string("cancel-session"),
                        "capability": .object([
                            "token": .string("cancel-capability"),
                            "expires_at": .string("2030-01-01T00:00:00Z"),
                            "hard_expires_at": .string("2030-01-01T01:00:00Z"),
                        ]),
                        "limits": .object([
                            "max_payload_bytes": .int(1_048_576),
                        ]),
                        "capabilities": .object([
                            "commands": .array([]),
                            "features": .object([
                                "session_presets": .array([]),
                            ]),
                        ]),
                    ]
                )
                try sendEnvelope(ready, to: accepted)
                _ = try receiveEnvelope(accepted)
                subscribed.signal()
                var byte: UInt8 = 0
                let received = Darwin.recv(accepted, &byte, 1, 0)
                lock.withLock { clientClosed = received == 0 }
            } catch {
                return
            }
        }
    }

    func waitUntilSubscribed() async -> Bool {
        await waitForSignal(subscribed)
    }

    func waitUntilClosed() async -> Bool {
        guard await waitForSignal(finished) else { return false }
        return lock.withLock { clientClosed }
    }

    func close() {
        let active = lock.withLock { connection }
        if active >= 0 {
            _ = Darwin.shutdown(active, SHUT_RDWR)
            _ = Darwin.close(active)
        }
        _ = Darwin.shutdown(listener, SHUT_RDWR)
        _ = Darwin.close(listener)
        _ = unlink(path)
    }
}

private func waitForSignal(_ semaphore: DispatchSemaphore) async -> Bool {
    await Task.detached { blockingWaitForSignal(semaphore) }.value
}

private func blockingWaitForSignal(_ semaphore: DispatchSemaphore) -> Bool {
    semaphore.wait(timeout: .now() + 2) == .success
}

private func receiveEnvelope(_ descriptor: Int32) throws -> NativeEnvelope {
    var header = [UInt8](repeating: 0, count: 4)
    guard receiveExactly(descriptor, bytes: &header) else {
        throw NativeTransportError("test peer did not receive a frame header")
    }
    let count = header.reduce(0) { $0 << 8 | Int($1) }
    var body = [UInt8](repeating: 0, count: count)
    guard receiveExactly(descriptor, bytes: &body) else {
        throw NativeTransportError("test peer did not receive a frame body")
    }
    return try NativeFrameCodec.decode(frame: Data(header + body))
}

private func sendEnvelope(
    _ envelope: NativeEnvelope,
    to descriptor: Int32
) throws {
    let frame = try NativeFrameCodec.encode(envelope)
    let sent = frame.withUnsafeBytes { bytes in
        Darwin.send(descriptor, bytes.baseAddress, bytes.count, 0)
    }
    guard sent == frame.count else {
        throw NativeTransportError("test peer did not send a complete frame")
    }
}

private final class RefusingUDSServer: @unchecked Sendable {
    private let descriptor: Int32
    private let path: String
    private let done = DispatchSemaphore(value: 0)

    init(path: String, envelope: NativeEnvelope) throws {
        self.path = path
        descriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw NativeTransportError("test socket failed") }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { bytes in
            bytes.copyBytes(from: Array(path.utf8) + [0])
        }
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard bound == 0, Darwin.listen(descriptor, 1) == 0 else {
            _ = Darwin.close(descriptor)
            throw NativeTransportError("test bind failed")
        }
        let done = self.done
        let frame = try NativeFrameCodec.encode(envelope)
        Thread.detachNewThread {
            let connection = Darwin.accept(self.descriptor, nil, nil)
            if connection >= 0 {
                if consumeFrame(connection) {
                    frame.withUnsafeBytes { bytes in
                        _ = Darwin.send(connection, bytes.baseAddress, bytes.count, 0)
                    }
                }
                _ = Darwin.close(connection)
            }
            done.signal()
        }
    }

    func finished() async -> Bool {
        await Task.detached { waitForRefusingServer(self.done) }.value
    }

    func close() {
        _ = Darwin.close(descriptor)
        _ = unlink(path)
    }
}

private func waitForRefusingServer(_ semaphore: DispatchSemaphore) -> Bool {
    semaphore.wait(timeout: .now() + 10) == .success
}

private func consumeFrame(_ descriptor: Int32) -> Bool {
    var header = [UInt8](repeating: 0, count: 4)
    guard receiveExactly(descriptor, bytes: &header) else { return false }
    let count = header.reduce(0) { $0 << 8 | Int($1) }
    var body = [UInt8](repeating: 0, count: count)
    return receiveExactly(descriptor, bytes: &body)
}

private func receiveExactly(_ descriptor: Int32, bytes: inout [UInt8]) -> Bool {
    var offset = 0
    let count = bytes.count
    while offset < count {
        let received = bytes.withUnsafeMutableBytes { buffer in
            Darwin.recv(descriptor, buffer.baseAddress!.advanced(by: offset), count - offset, 0)
        }
        guard received > 0 else { return false }
        offset += received
    }
    return true
}
