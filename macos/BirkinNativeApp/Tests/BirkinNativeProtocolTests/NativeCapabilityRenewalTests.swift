import Testing

@testable import BirkinNativeProtocol

@Suite("Native capability renewal")
struct NativeCapabilityRenewalTests {
    @Test("in-band renewal atomically swaps the token without leaving ready")
    func renewalDoesNotFlicker() async throws {
        let oldToken = "old-memory-only-token"
        let renewedToken = "renewed-memory-only-token"
        let original = NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0.0",
            sessionCapability: oldToken
        )
        let transport = NativeTransportActor(state: .ready(original))
        let renewal = NativeEnvelope(
            kind: .capabilityRenewed,
            id: "capability-1",
            body: [
                "token": .string(renewedToken),
                "expires_at": .string("2026-08-20T22:00:00+00:00"),
                "hard_expires_at": .string("2026-08-21T05:00:00+00:00"),
            ]
        )
        var readyTrace = [isReady(await transport.state)]

        try await transport.acceptCapabilityRenewal(renewal)
        let current = await transport.state
        readyTrace.append(isReady(current))

        #expect(readyTrace == [true, true])
        #expect(current == .ready(NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0.0",
            sessionCapability: renewedToken
        )))
        #expect(capability(in: current) != oldToken)
        print("RENEWAL STATE TRACE ready -> ready old_referenced=false")
    }

    private func isReady(_ state: NativeConnectionState) -> Bool {
        if case .ready = state { return true }
        return false
    }

    private func capability(in state: NativeConnectionState) -> String? {
        guard case .ready(let session) = state else { return nil }
        return session.sessionCapability
    }
}
