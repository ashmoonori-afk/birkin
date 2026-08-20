import Foundation

extension NativeTransportActor {
    func negotiate(
        socket: NativeSocket,
        hello: NativeHello,
        secret: String?,
        as transport: NativeTransportKind
    ) throws -> NativeHandshakeTranscript {
        let outbound = hello.envelope(bootstrapSecret: secret)
        try socket.send(NativeFrameCodec.encode(outbound))
        let inbound = try NativeFrameCodec.decode(frame: socket.receiveFrame())
        guard inbound.kind == .ready, inbound.inReplyTo == outbound.id else {
            throw NativeTransportError("server did not return correlated ready")
        }
        guard case .string(let wireTransport) = inbound.body["transport"],
              wireTransport == transport.rawValue,
              case .string(let instanceID) = inbound.body["instance_id"],
              case .string(let serverVersion) = inbound.body["server_version"],
              case .object(let capability) = inbound.body["capability"],
              case .string(let token) = capability["token"],
              case .string(let expiresAt) = capability["expires_at"],
              case .string(let hardExpiresAt) = capability["hard_expires_at"],
              case .object(let capabilities) = inbound.body["capabilities"],
              case .array(let commandValues) = capabilities["commands"],
              case .object(let features) = capabilities["features"],
              case .array(let presetValues) = features["session_presets"],
              let expiry = NativeProtocolDate.parse(expiresAt),
              let hardExpiry = NativeProtocolDate.parse(hardExpiresAt)
        else {
            throw NativeTransportError("ready body is missing transport session fields")
        }
        let commands = try commandValues.map { value in
            guard case .string(let command) = value else {
                throw NativeTransportError("ready command advertisement must contain strings")
            }
            return command
        }
        let presets = try presetValues.map { value in
            guard case .object(let preset) = value else {
                throw NativeTransportError("ready session presets must contain objects")
            }
            return try NativeSessionPreset.decode(preset)
        }.sorted { $0.order < $1.order }
        return NativeHandshakeTranscript(
            hello: outbound,
            ready: inbound,
            transport: transport,
            session: NativeReadySession(
                instanceID: instanceID,
                serverVersion: serverVersion,
                sessionCapability: token,
                capabilityExpiresAt: expiry,
                capabilityHardExpiresAt: hardExpiry,
                supportedCommands: Set(commands),
                sessionPresets: presets
            )
        )
    }
}

