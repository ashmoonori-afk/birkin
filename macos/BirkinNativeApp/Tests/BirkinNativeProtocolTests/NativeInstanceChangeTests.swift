import Testing

@testable import BirkinNativeProtocol

@Suite("Native reconnect instance identity")
struct NativeInstanceChangeTests {
    @Test("changed server instance discards held projection and requests a full replay")
    func instanceChangeResetsProjection() async {
        let oldSession = NativeReadySession(
            instanceID: "instance-old",
            serverVersion: "1.0.0",
            sessionCapability: "old-token"
        )
        let newSession = NativeReadySession(
            instanceID: "instance-new",
            serverVersion: "1.0.0",
            sessionCapability: "new-token"
        )
        let transport = NativeTransportActor(state: .ready(oldSession))
        await transport.retainProjection(
            cursor: 42,
            values: ["conversation": .string("stale")]
        )

        await transport.apply(.disconnect)
        await transport.apply(.connect)
        await transport.apply(.socketConnected(.uds))
        await transport.acceptNegotiated(newSession)

        #expect(await transport.heldProjection == nil)
        #expect(await transport.pendingReplayRequest == NativeReplayRequest(
            afterCursor: 0,
            knownInstanceID: nil,
            replay: true
        ))
        #expect(await transport.state == .replaying(newSession))

        await transport.replayCompleted()
        #expect(await transport.state == .ready(newSession))
    }
}
