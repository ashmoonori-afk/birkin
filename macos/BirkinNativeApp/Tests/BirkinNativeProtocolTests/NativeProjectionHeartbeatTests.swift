import Testing

@testable import BirkinNativeProtocol

@Suite("Native projection heartbeat")
struct NativeProjectionHeartbeatTests {
    @Test("pong authenticates the live projection session")
    func authenticatedPong() throws {
        let ping = NativeEnvelope(
            kind: .ping,
            id: "server-ping",
            body: ["sent_at": .string("2026-08-21T12:00:00Z")]
        )

        let pong = try NativeProjectionSubscription.pong(
            for: ping,
            sessionCapability: "memory-only-session-token"
        )

        #expect(pong.kind == .pong)
        #expect(pong.inReplyTo == ping.id)
        #expect(pong.body == [
            "sent_at": .string("2026-08-21T12:00:00Z"),
            "session_capability": .string("memory-only-session-token"),
        ])
    }
}
