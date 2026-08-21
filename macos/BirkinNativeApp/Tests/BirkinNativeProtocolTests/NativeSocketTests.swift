import Darwin
import Testing

@testable import BirkinNativeProtocol

@Suite("Native socket idle receive policy")
struct NativeSocketTests {
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
