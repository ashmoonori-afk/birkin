import Testing

@testable import BirkinNativeProtocol

@Suite("Native transport connection state")
struct NativeConnectionStateTests {
    private let session = NativeReadySession(
        instanceID: "instance-1",
        serverVersion: "1.0.0",
        sessionCapability: "memory-only-token"
    )

    @Test("UDS connection negotiates before becoming ready")
    func udsTransitions() {
        var state = NativeConnectionState.disconnected

        state = NativeConnectionReducer.reduce(state, .connect)
        #expect(state == .connecting)
        state = NativeConnectionReducer.reduce(state, .socketConnected(.uds))
        #expect(state == .negotiating(.uds))
        state = NativeConnectionReducer.reduce(state, .negotiated(session))
        #expect(state == .ready(session))
    }

    @Test("UDS failure enters a visible loopback fallback through negotiation")
    func fallbackTransitions() {
        var state = NativeConnectionState.connecting

        state = NativeConnectionReducer.reduce(
            state,
            .udsUnavailable(reason: "socket missing")
        )
        #expect(state == .fallback(.connecting(reason: "socket missing")))
        state = NativeConnectionReducer.reduce(state, .socketConnected(.loopback))
        #expect(state == .fallback(.negotiating))
        state = NativeConnectionReducer.reduce(state, .negotiated(session))
        #expect(state == .fallback(.ready(session)))
    }

    @Test("failure retains a diagnostic reason and disconnect clears it")
    func failureAndDisconnect() {
        var state = NativeConnectionReducer.reduce(
            .negotiating(.uds),
            .failed(reason: "peer closed")
        )
        #expect(state == .failed(reason: "peer closed"))

        state = NativeConnectionReducer.reduce(state, .disconnect)
        #expect(state == .disconnected)
    }

    @Test("actor serializes reducer transitions")
    func actorTransitions() async {
        let transport = NativeTransportActor()

        await transport.apply(.connect)
        await transport.apply(.socketConnected(.uds))

        #expect(await transport.state == .negotiating(.uds))
    }
}
