import Foundation

/// A full canonical replay followed by the live envelopes on the same socket.
public struct NativeProjectionSubscription: Sendable {
    public let session: NativeReadySession
    public let snapshot: NativeEnvelope
    public let messages: AsyncThrowingStream<NativeEnvelope, any Error>
    public let submit: @Sendable (NativeCommandRequest) throws -> Void
    public let replaying: Bool

    public init(
        session: NativeReadySession,
        snapshot: NativeEnvelope,
        messages: AsyncThrowingStream<NativeEnvelope, any Error>,
        submit: @escaping @Sendable (NativeCommandRequest) throws -> Void,
        replaying: Bool
    ) {
        self.session = session
        self.snapshot = snapshot
        self.messages = messages
        self.submit = submit
        self.replaying = replaying
    }

    static func pong(
        for ping: NativeEnvelope,
        sessionCapability: String
    ) throws -> NativeEnvelope {
        var body = ping.body
        try body.append(
            key: "session_capability",
            value: .string(sessionCapability)
        )
        return NativeEnvelope(
            kind: .pong,
            id: "app-pong-\(UUID().uuidString)",
            inReplyTo: ping.id,
            body: body
        )
    }

    static func controlResponse(
        for envelope: NativeEnvelope,
        capability: NativeProjectionCapability
    ) throws -> NativeEnvelope? {
        if envelope.kind == .capabilityRenewed {
            try capability.acceptRenewal(envelope)
            return nil
        }
        guard envelope.kind == .ping else { return nil }
        return try pong(
            for: envelope,
            sessionCapability: capability.current()
        )
    }
}

final class NativeProjectionCapability: @unchecked Sendable {
    private let lock = NSLock()
    private var token: String
    private let surface: String
    private let viewID: String

    init(_ token: String, surface: String, viewID: String) {
        self.token = token
        self.surface = surface
        self.viewID = viewID
    }

    func current() -> String {
        lock.withLock { token }
    }

    func commandEnvelope(for request: NativeCommandRequest) -> NativeEnvelope {
        request.envelope(
            sessionCapability: current(),
            surface: surface,
            viewID: viewID
        )
    }

    func acceptRenewal(_ envelope: NativeEnvelope) throws {
        guard envelope.kind == .capabilityRenewed,
              case .string(let replacement) = envelope.body["token"],
              case .string(let expiresAt) = envelope.body["expires_at"],
              case .string(let hardExpiresAt) = envelope.body["hard_expires_at"],
              !replacement.isEmpty,
              NativeProtocolDate.parse(expiresAt) != nil,
              NativeProtocolDate.parse(hardExpiresAt) != nil
        else {
            throw NativeTransportError("capability renewal is missing valid lease fields")
        }
        lock.withLock { token = replacement }
    }
}

extension NativeTransportActor {
    /// Opens the executable's long-lived UDS subscription. Reconnects always
    /// request a full canonical replay before live events are accepted.
    public func openProjectionSubscriptionUDS(
        socketPath: String,
        hello: NativeHello,
        sessionID: String? = nil,
        surfaceRevisions: [String: Int]? = nil,
        replaying: Bool
    ) throws -> NativeProjectionSubscription {
        apply(.connect)
        do {
            let socket = try NativeSocket.connectUDS(path: socketPath)
            apply(.socketConnected(.uds))
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                authentication: .uds
            )
            acceptNegotiated(transcript.session)
            if replaying {
                beginReplay(transcript.session)
            }
            let requestedSurfaces = surfaceRevisions ?? Dictionary(
                uniqueKeysWithValues: transcript.session.supportedSurfaces.map { ($0, 0) }
            )
            var surfaceBody: NativeJSONObject = [:]
            for (name, revision) in requestedSurfaces.sorted(by: { $0.key < $1.key }) {
                try surfaceBody.append(key: name, value: .int(revision))
            }
            let subscribe = NativeEnvelope(
                kind: .subscribe,
                id: "app-subscribe-\(UUID().uuidString)",
                body: [
                    "session_id": .string(sessionID ?? transcript.session.currentSessionID),
                    "after_cursor": .int(0),
                    "known_instance_id": .null,
                    "session_capability": .string(transcript.session.sessionCapability),
                    "surfaces": .object(surfaceBody),
                ]
            )
            try socket.send(NativeFrameCodec.encode(subscribe))
            let snapshot = try receiveSnapshot(
                socket: socket,
                sessionCapability: transcript.session.sessionCapability
            )
            let capability = NativeProjectionCapability(
                transcript.session.sessionCapability,
                surface: hello.surface,
                viewID: hello.viewID
            )
            let messages = AsyncThrowingStream<NativeEnvelope, any Error> { continuation in
                continuation.onTermination = { _ in socket.close() }
                Thread.detachNewThread {
                    defer { socket.close() }
                    do {
                        while true {
                            let envelope = try NativeFrameCodec.decode(
                                frame: socket.receiveFrame()
                            )
                            if let response = try NativeProjectionSubscription.controlResponse(
                                for: envelope,
                                capability: capability
                            ) {
                                try socket.send(NativeFrameCodec.encode(response))
                            } else {
                                continuation.yield(envelope)
                            }
                        }
                        continuation.finish()
                    } catch {
                        continuation.finish(throwing: error)
                    }
                }
            }
            return NativeProjectionSubscription(
                session: transcript.session,
                snapshot: snapshot,
                messages: messages,
                submit: { request in
                    try socket.send(NativeFrameCodec.encode(
                        capability.commandEnvelope(for: request)
                    ))
                },
                replaying: replaying
            )
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }

    private func receiveSnapshot(
        socket: NativeSocket,
        sessionCapability: String
    ) throws -> NativeEnvelope {
        while true {
            let envelope = try NativeFrameCodec.decode(frame: socket.receiveFrame())
            if envelope.kind == .snapshot { return envelope }
            if envelope.kind == .ping {
                try socket.send(NativeFrameCodec.encode(
                    try NativeProjectionSubscription.pong(
                        for: envelope,
                        sessionCapability: sessionCapability
                    )
                ))
                continue
            }
            throw NativeTransportError("projection subscription did not return a snapshot")
        }
    }
}
