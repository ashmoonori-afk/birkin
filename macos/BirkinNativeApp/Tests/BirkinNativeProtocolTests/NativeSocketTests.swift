import Darwin
import Dispatch
import Testing

@testable import BirkinNativeProtocol

@Suite("Native socket idle receive policy")
struct NativeSocketTests {
    @Test("close shuts down an acquired receive lease and rejects later leases")
    func closeInterruptsReceiveLease() throws {
        let pair = try SocketPair()
        defer { pair.closePeer() }
        let ownership = NativeSocketDescriptorOwnership(descriptor: pair.owned)
        let receiveLease = try ownership.lease()

        ownership.close()

        var byte: UInt8 = 0
        #expect(Darwin.recv(receiveLease.descriptor, &byte, 1, 0) == 0)
        #expect(throws: NativeTransportError.self) {
            _ = try ownership.lease()
        }
    }

    @Test("close shuts down an acquired send lease without touching a reused descriptor")
    func closeDoesNotReuseDescriptorDuringSend() throws {
        let pair = try SocketPair()
        defer { pair.closePeer() }
        let ownership = NativeSocketDescriptorOwnership(descriptor: pair.owned)
        let sendLease = try ownership.lease()

        ownership.close()
        let replacement = try SocketPair()
        defer { replacement.closeBoth() }

        var byte: UInt8 = 0x41
        #expect(Darwin.send(sendLease.descriptor, &byte, 1, 0) == -1)
        #expect(fcntl(replacement.owned, F_GETFD) >= 0)
    }

    @Test("competing close calls atomically take descriptor ownership once")
    func closeIsIdempotent() throws {
        let pair = try SocketPair()
        defer { pair.closePeer() }
        let ownership = NativeSocketDescriptorOwnership(descriptor: pair.owned)
        let start = DispatchSemaphore(value: 0)
        let finished = DispatchGroup()

        for _ in 0..<16 {
            finished.enter()
            DispatchQueue.global().async {
                start.wait()
                ownership.close()
                finished.leave()
            }
        }
        for _ in 0..<16 { start.signal() }
        #expect(finished.wait(timeout: .now() + 1) == .success)
        #expect(throws: NativeTransportError.self) {
            _ = try ownership.lease()
        }
    }

    @Test("transient receive timeouts remain below the heartbeat failure budget")
    func idleTimeoutBudget() {
        let budget = NativeSocket.receiveTimeoutSeconds
            * NativeSocket.maximumConsecutiveIdleTimeouts

        #expect(budget > 30)
        for timeout in 1...NativeSocket.maximumConsecutiveIdleTimeouts {
            #expect(NativeSocket.shouldRetryReceive(
                error: EAGAIN,
                consecutiveTimeouts: timeout
            ))
        }
        #expect(!NativeSocket.shouldRetryReceive(
            error: EWOULDBLOCK,
            consecutiveTimeouts: NativeSocket.maximumConsecutiveIdleTimeouts + 1
        ))
        #expect(!NativeSocket.shouldRetryReceive(
            error: ECONNRESET,
            consecutiveTimeouts: 1
        ))
    }
}

private final class SocketPair: @unchecked Sendable {
    let owned: Int32
    private let peer: Int32

    init() throws {
        var descriptors = [Int32](repeating: -1, count: 2)
        guard socketpair(AF_UNIX, SOCK_STREAM, 0, &descriptors) == 0 else {
            throw NativeTransportError("socketpair failed")
        }
        owned = descriptors[0]
        peer = descriptors[1]
        var enabled: Int32 = 1
        _ = setsockopt(
            owned,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &enabled,
            socklen_t(MemoryLayout<Int32>.size)
        )
    }

    func closePeer() {
        _ = Darwin.close(peer)
    }

    func closeBoth() {
        _ = Darwin.close(owned)
        _ = Darwin.close(peer)
    }
}
