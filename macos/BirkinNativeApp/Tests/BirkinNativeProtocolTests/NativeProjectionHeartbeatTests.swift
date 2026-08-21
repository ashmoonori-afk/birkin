import Testing

@testable import BirkinNativeProtocol

@Suite("Native projection heartbeat")
struct NativeProjectionHeartbeatTests {
    @Test("live renewal authenticates every later heartbeat with the replacement token")
    func renewedAuthenticatedPongs() throws {
        let capability = NativeProjectionCapability(
            "initial-token",
            surface: "macos",
            viewID: "main"
        )
        let renewal = NativeEnvelope(
            kind: .capabilityRenewed,
            id: "capability-renewal",
            body: [
                "token": .string("replacement-token"),
                "expires_at": .string("2026-08-21T22:00:00Z"),
                "hard_expires_at": .string("2026-08-22T05:00:00Z"),
            ]
        )
        #expect(try NativeProjectionSubscription.controlResponse(
            for: renewal,
            capability: capability
        ) == nil)
        let staleCommand = NativeCommandRequest(
            frameID: "command-frame",
            commandID: "command-1",
            expectedCursor: 1,
            commandType: "conversation.send",
            payload: [:],
            sessionCapability: "initial-token",
            viewID: "caller-local"
        )
        let authenticated = capability.commandEnvelope(for: staleCommand)
        #expect(
            authenticated.body["session_capability"]
                == .string("replacement-token")
        )
        let renewedContext = try commandContext(authenticated)
        #expect(renewedContext["surface"] == .string("macos"))
        #expect(renewedContext["view_id"] == .string("main"))

        for pingID in ["server-ping-1", "server-ping-2"] {
            let ping = NativeEnvelope(
                kind: .ping,
                id: pingID,
                body: ["sent_at": .string("2026-08-21T12:00:00Z")]
            )
            let response = try NativeProjectionSubscription.controlResponse(
                for: ping,
                capability: capability
            )
            let pong = try #require(response)
            #expect(pong.inReplyTo == pingID)
            #expect(pong.body["session_capability"] == .string("replacement-token"))
        }
    }

    @Test("caller-local command identity cannot replace negotiated wire scope")
    func immutableCommandScope() throws {
        let capability = NativeProjectionCapability(
            "connection-token",
            surface: "negotiated-surface",
            viewID: "negotiated-view"
        )
        let request = NativeCommandRequest(
            frameID: "command-frame",
            commandID: "command-1",
            expectedCursor: 1,
            commandType: "conversation.send",
            payload: [:],
            sessionCapability: "caller-token",
            viewID: "caller-spoof-must-stay-local"
        )

        let callerContext = try commandContext(request.envelope)
        let wire = capability.commandEnvelope(for: request)
        let wireContext = try commandContext(wire)

        #expect(request.viewID == "caller-spoof-must-stay-local")
        #expect(callerContext["view_id"] == .string(request.viewID))
        #expect(wire.body["session_capability"] == .string("connection-token"))
        #expect(wireContext["surface"] == .string("negotiated-surface"))
        #expect(wireContext["view_id"] == .string("negotiated-view"))
    }

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

private func commandContext(_ envelope: NativeEnvelope) throws -> NativeJSONObject {
    guard case .object(let command) = envelope.body["command"],
          case .object(let context) = command["client_context"]
    else {
        throw NativeTransportError("command envelope has no client context")
    }
    return context
}
