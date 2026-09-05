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
    public var diagnosticsLabel: String { "연결 세부 정보" }

    public var renderSignature: String {
        [identifier, title, transportLabel, detail, symbolName, tone.rawValue]
            .joined(separator: "|")
    }

    public init(state: NativeConnectionState) {
        switch state {
        case .disconnected:
            self = Self.make(
                "disconnected", "연결 끊김", "연결 없음",
                "Birkin이 다시 연결될 때까지 변경 작업을 수행할 수 없습니다.",
                "bolt.slash", .warning
            )
        case .connecting:
            self = Self.make(
                "connecting", "연결 중", "Unix 소켓",
                "보호된 로컬 연결을 여는 중입니다.",
                "arrow.triangle.2.circlepath", .progress
            )
        case .negotiating(let transport):
            let label = transport == .uds ? "Unix 소켓" : "전용 로컬 연결"
            self = Self.make(
                "handshaking-\(transport.rawValue)", "연결 중", label,
                "로컬 연결을 인증하고 있습니다.",
                "checkmark.shield", .progress
            )
        case .ready:
            self = Self.make(
                "ready-uds", "로컬 · 보호됨", "Unix 소켓",
                "로컬 Python 서비스에 연결되었습니다.",
                "lock.shield", .healthy
            )
        case .replaying:
            self = Self.make(
                "replaying", "다시 연결 중", "Unix 소켓",
                "변경 작업을 다시 시작하기 전에 최신 상태를 복원하고 있습니다.",
                "clock.arrow.circlepath", .progress
            )
        case .fallback(let fallback):
            switch fallback {
            case .connecting(let reason):
                self = Self.make(
                    "fallback-connecting", "연결 중", "전용 로컬 대체 연결",
                    "Unix 소켓을 사용할 수 없어 대체 연결을 시도합니다: \(Self.bounded(reason))",
                    "network.badge.shield.half.filled", .fallback
                )
            case .negotiating:
                self = Self.make(
                    "fallback-handshaking", "연결 중", "전용 로컬 대체 연결",
                    "전용 로컬 연결을 인증하고 있습니다.",
                    "network.badge.shield.half.filled", .fallback
                )
            case .ready:
                self = Self.make(
                    "ready-loopback", "로컬 · 보호됨", "전용 로컬 대체 연결",
                    "Unix 소켓을 사용할 수 없어 전용 로컬 연결로 연결되었습니다.",
                    "network.badge.shield.half.filled", .fallback
                )
            }
        case .failed(let reason):
            let title = reason.localizedCaseInsensitiveContains("version")
                ? "버전 불일치" : "서비스를 사용할 수 없음"
            self = Self.make(
                "failed", title, "연결 없음", Self.bounded(reason),
                "exclamationmark.octagon", .failure
            )
        }
    }

    public static func reconnecting(
        attempt: Int,
        retryAfter: TimeInterval
    ) -> ConnectionPresentation {
        make(
            "reconnecting", "다시 연결 중", "재시도 대기",
            "\(String(format: "%.1f", max(0, retryAfter)))초 후 \(max(1, attempt))번째 연결을 시도합니다.",
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
