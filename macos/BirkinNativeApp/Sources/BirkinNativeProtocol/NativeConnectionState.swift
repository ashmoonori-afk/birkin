/// The local transport selected for a native bridge connection.
public enum NativeTransportKind: String, Equatable, Sendable {
    case uds
    case loopback
}

/// Authenticated values retained only for the lifetime of one connection.
public struct NativeReadySession: Equatable, Sendable {
    public let instanceID: String
    public let serverVersion: String
    public let sessionCapability: String

    public init(instanceID: String, serverVersion: String, sessionCapability: String) {
        self.instanceID = instanceID
        self.serverVersion = serverVersion
        self.sessionCapability = sessionCapability
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
    case fallback(NativeLoopbackFallbackState)
    case failed(reason: String)
}

public enum NativeConnectionAction: Equatable, Sendable {
    case connect
    case socketConnected(NativeTransportKind)
    case udsUnavailable(reason: String)
    case negotiated(NativeReadySession)
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
        case (.connecting, .failed(let reason)),
            (.negotiating, .failed(let reason)),
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

    public init(state: NativeConnectionState = .disconnected) {
        self.state = state
    }

    public func apply(_ action: NativeConnectionAction) {
        state = NativeConnectionReducer.reduce(state, action)
    }
}
