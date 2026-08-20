import Foundation

/// The local transport selected for a native bridge connection.
public enum NativeTransportKind: String, Equatable, Sendable {
    case uds
    case loopback
}

/// Authenticated values retained only for the lifetime of one connection.
public struct NativeProjectionCheckpoint: Equatable, Sendable {
    public let instanceID: String
    public let cursor: Int
    public let values: [String: NativeJSONValue]
}

public struct NativeReplayRequest: Equatable, Sendable {
    public let afterCursor: Int
    public let knownInstanceID: String?
    public let replay: Bool

    public init(afterCursor: Int, knownInstanceID: String?, replay: Bool) {
        self.afterCursor = afterCursor
        self.knownInstanceID = knownInstanceID
        self.replay = replay
    }
}

public struct NativeReadySession: Equatable, Sendable {
    public let instanceID: String
    public let serverVersion: String
    public let currentSessionID: String
    public let sessionCapability: String
    public let capabilityExpiresAt: Date?
    public let capabilityHardExpiresAt: Date?
    public let supportedCommands: Set<String>
    public let sessionPresets: [NativeSessionPreset]
    public let supportedSurfaces: Set<String>
    public let maxPayloadBytes: Int
    public let voiceInputAvailable: Bool

    public init(
        instanceID: String,
        serverVersion: String,
        currentSessionID: String = "",
        sessionCapability: String,
        capabilityExpiresAt: Date? = nil,
        capabilityHardExpiresAt: Date? = nil,
        supportedCommands: Set<String> = [],
        sessionPresets: [NativeSessionPreset] = [],
        supportedSurfaces: Set<String> = [],
        maxPayloadBytes: Int = NativePayloadSizing.defaultMaxPayloadBytes,
        voiceInputAvailable: Bool = false
    ) {
        self.instanceID = instanceID
        self.serverVersion = serverVersion
        self.currentSessionID = currentSessionID
        self.sessionCapability = sessionCapability
        self.capabilityExpiresAt = capabilityExpiresAt
        self.capabilityHardExpiresAt = capabilityHardExpiresAt
        self.supportedCommands = supportedCommands
        self.sessionPresets = sessionPresets
        self.supportedSurfaces = supportedSurfaces
        self.maxPayloadBytes = maxPayloadBytes
        self.voiceInputAvailable = voiceInputAvailable
    }

    public func hasLiveCapability(at date: Date) -> Bool {
        guard !sessionCapability.isEmpty,
              let capabilityExpiresAt,
              let capabilityHardExpiresAt else { return false }
        return date < capabilityExpiresAt && date < capabilityHardExpiresAt
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.instanceID == rhs.instanceID
            && lhs.serverVersion == rhs.serverVersion
            && lhs.currentSessionID == rhs.currentSessionID
            && lhs.sessionCapability == rhs.sessionCapability
            && lhs.supportedCommands == rhs.supportedCommands
            && lhs.sessionPresets == rhs.sessionPresets
            && lhs.supportedSurfaces == rhs.supportedSurfaces
            && lhs.maxPayloadBytes == rhs.maxPayloadBytes
            && lhs.voiceInputAvailable == rhs.voiceInputAvailable
    }
}

/// Loopback remains explicit after negotiation so callers never present it as
/// the preferred same-user Unix transport.
public enum NativeLoopbackFallbackState: Equatable, Sendable {
    case connecting(reason: String)
    case negotiating
    case ready(NativeReadySession)
}

public enum NativeConnectionState: Equatable, Sendable {
    case disconnected
    case connecting
    case negotiating(NativeTransportKind)
    case ready(NativeReadySession)
    case replaying(NativeReadySession)
    case fallback(NativeLoopbackFallbackState)
    case failed(reason: String)
}

public enum NativeConnectionAction: Equatable, Sendable {
    case connect
    case socketConnected(NativeTransportKind)
    case udsUnavailable(reason: String)
    case negotiated(NativeReadySession)
    case instanceChanged(NativeReadySession)
    case replayStarted(NativeReadySession)
    case replayCompleted
    case capabilityRenewed(token: String)
    case failed(reason: String)
    case disconnect
}

/// Pure connection lifecycle reducer. Invalid or stale actions leave state
/// unchanged instead of manufacturing a connection transition.
public enum NativeConnectionReducer {
    public static func reduce(
        _ state: NativeConnectionState,
        _ action: NativeConnectionAction
    ) -> NativeConnectionState {
        switch (state, action) {
        case (_, .disconnect):
            return .disconnected
        case (.disconnected, .connect), (.failed, .connect):
            return .connecting
        case (.connecting, .socketConnected(.uds)):
            return .negotiating(.uds)
        case (.connecting, .udsUnavailable(let reason)):
            return .fallback(.connecting(reason: reason))
        case (.fallback(.connecting), .socketConnected(.loopback)):
            return .fallback(.negotiating)
        case (.negotiating(.uds), .negotiated(let session)):
            return .ready(session)
        case (.fallback(.negotiating), .negotiated(let session)):
            return .fallback(.ready(session))
        case (.negotiating, .instanceChanged(let session)),
            (.fallback(.negotiating), .instanceChanged(let session)),
            (.ready, .replayStarted(let session)):
            return .replaying(session)
        case (.replaying(let session), .replayCompleted):
            return .ready(session)
        case (.ready(let session), .capabilityRenewed(let token)):
            return .ready(session.replacingCapability(with: token))
        case (.fallback(.ready(let session)), .capabilityRenewed(let token)):
            return .fallback(.ready(session.replacingCapability(with: token)))
        case (.connecting, .failed(let reason)),
            (.negotiating, .failed(let reason)),
            (.replaying, .failed(let reason)),
            (.fallback, .failed(let reason)):
            return .failed(reason: reason)
        default:
            return state
        }
    }
}

/// Actor boundary for serialized transport lifecycle changes.
public actor NativeTransportActor {
    public private(set) var state: NativeConnectionState
    public private(set) var heldProjection: NativeProjectionCheckpoint?
    public private(set) var pendingReplayRequest: NativeReplayRequest?
    private var lastInstanceID: String?

    public init(state: NativeConnectionState = .disconnected) {
        self.state = state
        self.heldProjection = nil
        self.pendingReplayRequest = nil
        switch state {
        case .ready(let session), .replaying(let session), .fallback(.ready(let session)):
            self.lastInstanceID = session.instanceID
        default:
            self.lastInstanceID = nil
        }
    }

    public func apply(_ action: NativeConnectionAction) {
        state = NativeConnectionReducer.reduce(state, action)
    }

    public func retainProjection(cursor: Int, values: [String: NativeJSONValue]) {
        guard let lastInstanceID else { return }
        heldProjection = NativeProjectionCheckpoint(
            instanceID: lastInstanceID,
            cursor: cursor,
            values: values
        )
    }

    public func acceptNegotiated(_ session: NativeReadySession) {
        if let lastInstanceID, lastInstanceID != session.instanceID {
            heldProjection = nil
            pendingReplayRequest = NativeReplayRequest(
                afterCursor: 0,
                knownInstanceID: nil,
                replay: true
            )
            state = NativeConnectionReducer.reduce(state, .instanceChanged(session))
        } else {
            pendingReplayRequest = nil
            state = NativeConnectionReducer.reduce(state, .negotiated(session))
        }
        lastInstanceID = session.instanceID
    }

    public func beginReplay(_ session: NativeReadySession) {
        pendingReplayRequest = NativeReplayRequest(
            afterCursor: 0,
            knownInstanceID: nil,
            replay: true
        )
        state = NativeConnectionReducer.reduce(state, .replayStarted(session))
    }

    public func replayCompleted() {
        state = NativeConnectionReducer.reduce(state, .replayCompleted)
        pendingReplayRequest = nil
    }

    public func acceptCapabilityRenewal(_ envelope: NativeEnvelope) throws {
        guard envelope.kind == .capabilityRenewed,
              case .string(let token) = envelope.body["token"],
              case .string(let expiresAt) = envelope.body["expires_at"],
              case .string(let hardExpiresAt) = envelope.body["hard_expires_at"],
              !token.isEmpty,
              let expiry = NativeProtocolDate.parse(expiresAt),
              let hardExpiry = NativeProtocolDate.parse(hardExpiresAt)
        else {
            throw NativeTransportError("capability renewal is missing valid lease fields")
        }
        state = state.replacingCapability(
            token: token,
            expiresAt: expiry,
            hardExpiresAt: hardExpiry
        )
    }
}

private extension NativeConnectionState {
    func replacingCapability(
        token: String,
        expiresAt: Date,
        hardExpiresAt: Date
    ) -> NativeConnectionState {
        switch self {
        case .ready(let session):
            return .ready(session.replacingCapability(
                with: token,
                expiresAt: expiresAt,
                hardExpiresAt: hardExpiresAt
            ))
        case .fallback(.ready(let session)):
            return .fallback(.ready(session.replacingCapability(
                with: token,
                expiresAt: expiresAt,
                hardExpiresAt: hardExpiresAt
            )))
        default:
            return self
        }
    }
}

private extension NativeReadySession {
    func replacingCapability(
        with token: String,
        expiresAt: Date? = nil,
        hardExpiresAt: Date? = nil
    ) -> NativeReadySession {
        NativeReadySession(
            instanceID: instanceID,
            serverVersion: serverVersion,
            currentSessionID: currentSessionID,
            sessionCapability: token,
            capabilityExpiresAt: expiresAt ?? capabilityExpiresAt,
            capabilityHardExpiresAt: hardExpiresAt ?? capabilityHardExpiresAt,
            supportedCommands: supportedCommands,
            sessionPresets: sessionPresets,
            supportedSurfaces: supportedSurfaces,
            maxPayloadBytes: maxPayloadBytes,
            voiceInputAvailable: voiceInputAvailable
        )
    }
}
