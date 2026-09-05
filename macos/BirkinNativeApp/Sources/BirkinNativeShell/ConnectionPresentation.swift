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
    private let locale: Locale

    public var diagnosticsLabel: String {
        NativeLocalization.string("Show Diagnostics", locale: locale)
    }
    public var actionLabel: String {
        identifier.hasPrefix("failed-embedded_")
            ? NativeLocalization.string("Retry", locale: locale)
            : diagnosticsLabel
    }

    public var renderSignature: String {
        [identifier, title, transportLabel, detail, symbolName, tone.rawValue]
            .joined(separator: "|")
    }

    public init(
        state: NativeConnectionState,
        locale: Locale = NativeLocalization.currentLocale
    ) {
        func text(_ key: String) -> String {
            NativeLocalization.string(key, locale: locale)
        }
        func make(
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
                tone: tone,
                locale: locale
            )
        }

        switch state {
        case .disconnected:
            self = make(
                "disconnected", text("DISCONNECTED"), text("No transport"),
                text("Mutations are unavailable until Birkin reconnects."),
                "bolt.slash", .warning
            )
        case .connecting:
            self = make(
                "connecting", text("CONNECTING"), text("Unix socket"),
                text("Opening a private local connection."),
                "arrow.triangle.2.circlepath", .progress
            )
        case .negotiating(let transport):
            let label = transport == .uds
                ? text("Unix socket") : text("Private loopback")
            self = make(
                "handshaking-\(transport.rawValue)", text("CONNECTING"), label,
                text("Authenticating and negotiating the local protocol."),
                "checkmark.shield", .progress
            )
        case .ready:
            self = make(
                "ready-uds", text("LOCAL · PRIVATE"), text("Unix socket"),
                text("Connected to the local Python authority."),
                "lock.shield", .healthy
            )
        case .replaying:
            self = make(
                "replaying", text("RECONNECTING"), text("Unix socket"),
                text("Replaying the canonical projection before mutations resume."),
                "clock.arrow.circlepath", .progress
            )
        case .fallback(let fallback):
            switch fallback {
            case .connecting(let reason):
                self = make(
                    "fallback-connecting", text("CONNECTING"),
                    text("Private loopback fallback"),
                    NativeLocalization.string(
                        "Unix socket unavailable: %@",
                        locale: locale,
                        Self.bounded(reason)
                    ),
                    "network.badge.shield.half.filled", .fallback
                )
            case .negotiating:
                self = make(
                    "fallback-handshaking", text("CONNECTING"),
                    text("Private loopback fallback"),
                    text("Authenticating the private loopback connection."),
                    "network.badge.shield.half.filled", .fallback
                )
            case .ready:
                self = make(
                    "ready-loopback", text("LOCAL · PRIVATE"),
                    text("Private loopback fallback"),
                    text("Connected by loopback because the Unix socket was unavailable."),
                    "network.badge.shield.half.filled", .fallback
                )
            }
        case .failed(let reason):
            let diagnosis = Self.bridgeDiagnosis(reason)
            let title = reason.localizedCaseInsensitiveContains("version")
                ? text("VERSION MISMATCH") : text("BACKEND UNAVAILABLE")
            self = make(
                diagnosis.map { "failed-\($0.code)" } ?? "failed",
                title,
                text("No transport"),
                Self.bounded(diagnosis?.message ?? reason),
                "exclamationmark.octagon", .failure
            )
        }
    }

    public static func reconnecting(
        attempt: Int,
        retryAfter: TimeInterval,
        locale: Locale = NativeLocalization.currentLocale
    ) -> ConnectionPresentation {
        ConnectionPresentation(
            identifier: "reconnecting",
            title: NativeLocalization.string("RECONNECTING", locale: locale),
            transportLabel: NativeLocalization.string("Backoff", locale: locale),
            detail: NativeLocalization.string(
                "Attempt %lld in %.1f seconds.",
                locale: locale,
                Int64(max(1, attempt)),
                max(0, retryAfter)
            ),
            symbolName: "arrow.clockwise.circle",
            tone: .progress,
            locale: locale
        )
    }

    private init(
        identifier: String,
        title: String,
        transportLabel: String,
        detail: String,
        symbolName: String,
        tone: ConnectionTone,
        locale: Locale
    ) {
        self.identifier = identifier
        self.title = title
        self.transportLabel = transportLabel
        self.detail = detail
        self.symbolName = symbolName
        self.tone = tone
        self.locale = locale
    }

    private static func bounded(_ reason: String) -> String {
        String(reason.prefix(160))
    }

    private static func bridgeDiagnosis(_ reason: String) -> (code: String, message: String)? {
        let prefix = "code="
        guard reason.hasPrefix(prefix),
              let separator = reason.firstIndex(of: " ") else { return nil }
        let code = String(reason[reason.index(reason.startIndex, offsetBy: prefix.count)..<separator])
        let allowed = Set(OwnedBridgeDiscoveryError.Code.allCases.map(\.rawValue))
            .union(["embedded_launch_failed", "embedded_readiness_invalid"])
        guard allowed.contains(code) else { return nil }
        let remainder = reason[reason.index(after: separator)...]
        let message = remainder.hasPrefix("message=")
            ? String(remainder.dropFirst("message=".count)) : String(remainder)
        return (code, message)
    }
}
