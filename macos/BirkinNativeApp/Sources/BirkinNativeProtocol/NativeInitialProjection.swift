import Foundation

/// The authenticated ready state and first canonical snapshot used to boot the
/// packaged application. The socket remains private to the protocol module.
public struct NativeInitialProjection: Sendable {
    public let session: NativeReadySession
    public let snapshot: NativeEnvelope

    public init(session: NativeReadySession, snapshot: NativeEnvelope) {
        self.session = session
        self.snapshot = snapshot
    }
}

extension NativeTransportActor {
    public func loadInitialProjectionUDS(
        socketPath: String,
        hello: NativeHello,
        sessionID: String
    ) throws -> NativeInitialProjection {
        apply(.connect)
        do {
            let socket = try NativeSocket.connectUDS(path: socketPath)
            defer { socket.close() }
            apply(.socketConnected(.uds))
            let transcript = try negotiate(
                socket: socket,
                hello: hello,
                secret: nil,
                as: .uds
            )
            acceptNegotiated(transcript.session)
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
            let snapshot = try NativeFrameCodec.decode(frame: socket.receiveFrame())
            guard snapshot.kind == .snapshot else {
                throw NativeTransportError("initial subscription did not return a snapshot")
            }
            return NativeInitialProjection(session: transcript.session, snapshot: snapshot)
        } catch {
            apply(.failed(reason: String(describing: error)))
            throw error
        }
    }
}
