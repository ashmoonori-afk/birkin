import Foundation

/// A full canonical replay followed by the live envelopes on the same socket.
public struct NativeProjectionSubscription: Sendable {
    public let session: NativeReadySession
    public let snapshot: NativeEnvelope
    public let messages: AsyncThrowingStream<NativeEnvelope, any Error>
    public let replaying: Bool

    public init(
        session: NativeReadySession,
        snapshot: NativeEnvelope,
        messages: AsyncThrowingStream<NativeEnvelope, any Error>,
        replaying: Bool
    ) {
        self.session = session
        self.snapshot = snapshot
        self.messages = messages
        self.replaying = replaying
    }
}

extension NativeTransportActor {
    /// Opens the executable's long-lived UDS subscription. Reconnects always
    /// request a full canonical replay before live events are accepted.
    public func openProjectionSubscriptionUDS(
        socketPath: String,
        hello: NativeHello,
        sessionID: String,
        replaying: Bool
    ) throws -> NativeProjectionSubscription {
        apply(.connect)
        do {
            let socket = try NativeSocket.connectUDS(path: socketPath)
            apply(.socketConnected(.uds))
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                secret: nil,
                as: .uds
            )
            acceptNegotiated(transcript.session)
            if replaying {
                beginReplay(transcript.session)
            }
            let subscribe = NativeEnvelope(
                kind: .subscribe,
                id: "app-subscribe-\(UUID().uuidString)",
                body: [
                    "session_id": .string(sessionID),
                    "after_cursor": .int(0),
                    "known_instance_id": .null,
                    "session_capability": .string(transcript.session.sessionCapability),
                    "surfaces": .object([:]),
                ]
            )
            try socket.send(NativeFrameCodec.encode(subscribe))
            let snapshot = try receiveSnapshot(socket: socket)
            let messages = AsyncThrowingStream<NativeEnvelope, any Error> { continuation in
                continuation.onTermination = { _ in socket.close() }
                Task.detached {
                    defer { socket.close() }
                    do {
                        while !Task.isCancelled {
                            let envelope = try NativeFrameCodec.decode(
                                frame: socket.receiveFrame()
                            )
                            if envelope.kind == .ping {
                                try socket.send(NativeFrameCodec.encode(NativeEnvelope(
                                    kind: .pong,
                                    id: "app-pong-\(UUID().uuidString)",
                                    inReplyTo: envelope.id,
                                    body: envelope.body
                                )))
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
                replaying: replaying
            )
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }

    private func receiveSnapshot(socket: NativeSocket) throws -> NativeEnvelope {
        while true {
            let envelope = try NativeFrameCodec.decode(frame: socket.receiveFrame())
            if envelope.kind == .snapshot { return envelope }
            if envelope.kind == .ping {
                try socket.send(NativeFrameCodec.encode(NativeEnvelope(
                    kind: .pong,
                    id: "app-pong-\(UUID().uuidString)",
                    inReplyTo: envelope.id,
                    body: envelope.body
                )))
                continue
            }
            throw NativeTransportError("projection subscription did not return a snapshot")
        }
    }
}
