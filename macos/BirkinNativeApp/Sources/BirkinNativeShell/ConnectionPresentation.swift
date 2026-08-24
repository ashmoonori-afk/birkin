import BirkinNativeProtocol
import Foundation

public enum ConnectionTone: String, Equatable, Sendable {
    case neutral
    case progress
    case healthy
    case fallback
    case warning
    case failure
}

public struct ConnectionPresentation: Equatable, Sendable {
    public let identifier: String
    public let title: String
    public let transportLabel: String
    public let detail: String
    public let symbolName: String
    public let tone: ConnectionTone
    public var diagnosticsLabel: String { "Show Diagnostics" }

    public var renderSignature: String {
        [identifier, title, transportLabel, detail, symbolName, tone.rawValue]
            .joined(separator: "|")
    }

    public init(state: NativeConnectionState) {
        switch state {
        case .disconnected:
            self = Self.make(
                "disconnected", "DISCONNECTED", "No transport",
                "Mutations are unavailable until Birkin reconnects.",
                "bolt.slash", .warning
            )
        case .connecting:
            self = Self.make(
                "connecting", "CONNECTING", "Unix socket",
                "Opening a private local connection.",
                "arrow.triangle.2.circlepath", .progress
            )
        case .negotiating(let transport):
            let label = transport == .uds ? "Unix socket" : "Private loopback"
            self = Self.make(
                "handshaking-\(transport.rawValue)", "CONNECTING", label,
                "Authenticating and negotiating the local protocol.",
                "checkmark.shield", .progress
            )
        case .ready:
            self = Self.make(
                "ready-uds", "LOCAL · PRIVATE", "Unix socket",
                "Connected to the local Python authority.",
                "lock.shield", .healthy
            )
        case .replaying:
            self = Self.make(
                "replaying", "RECONNECTING", "Unix socket",
                "Replaying the canonical projection before mutations resume.",
                "clock.arrow.circlepath", .progress
            )
        case .fallback(let fallback):
            switch fallback {
            case .connecting(let reason):
                self = Self.make(
                    "fallback-connecting", "CONNECTING", "Private loopback fallback",
                    "Unix socket unavailable: \(Self.bounded(reason))",
                    "network.badge.shield.half.filled", .fallback
                )
            case .negotiating:
                self = Self.make(
                    "fallback-handshaking", "CONNECTING", "Private loopback fallback",
                    "Authenticating the private loopback connection.",
                    "network.badge.shield.half.filled", .fallback
                )
            case .ready:
                self = Self.make(
                    "ready-loopback", "LOCAL · PRIVATE", "Private loopback fallback",
                    "Connected by loopback because the Unix socket was unavailable.",
                    "network.badge.shield.half.filled", .fallback
                )
            }
        case .failed(let reason):
            let title = reason.localizedCaseInsensitiveContains("version")
                ? "VERSION MISMATCH" : "BACKEND UNAVAILABLE"
            self = Self.make(
                "failed", title, "No transport", Self.bounded(reason),
                "exclamationmark.octagon", .failure
            )
        }
    }

    public static func reconnecting(
        attempt: Int,
        retryAfter: TimeInterval
    ) -> ConnectionPresentation {
        make(
            "reconnecting", "RECONNECTING", "Backoff",
            "Attempt \(max(1, attempt)) in \(String(format: "%.1f", max(0, retryAfter))) seconds.",
            "arrow.clockwise.circle", .progress
        )
    }

    private static func make(
        _ identifier: String,
        _ title: String,
        _ transport: String,
        _ detail: String,
        _ symbol: String,
        _ tone: ConnectionTone
    ) -> ConnectionPresentation {
        ConnectionPresentation(
            identifier: identifier,
            title: title,
            transportLabel: transport,
            detail: detail,
            symbolName: symbol,
            tone: tone
        )
    }

    private init(
        identifier: String,
        title: String,
        transportLabel: String,
        detail: String,
        symbolName: String,
        tone: ConnectionTone
    ) {
        self.identifier = identifier
        self.title = title
        self.transportLabel = transportLabel
        self.detail = detail
        self.symbolName = symbolName
        self.tone = tone
    }

    private static func bounded(_ reason: String) -> String {
        String(reason.prefix(160))
    }
}
