import BirkinNativeProtocol
import SwiftUI

public enum DesktopMenuDestination: Equatable, Hashable, Sendable {
    case connection
    case session(id: String)
    case approvals
}

public enum DesktopMenuItemKind: Equatable, Sendable {
    case navigate
}

public struct DesktopMenuItem: Equatable, Identifiable, Sendable {
    public let title: String
    public let destination: DesktopMenuDestination
    public let kind: DesktopMenuItemKind = .navigate

    public var id: DesktopMenuDestination { destination }
}

/// Presentation-only menu data. Items carry routes and cannot carry commands or decisions.
public struct DesktopMenuModel: Equatable, Sendable {
    public let connectionTitle: String
    public let items: [DesktopMenuItem]

    public init(
        connection: NativeConnectionState,
        sessionID: String?,
        pendingApprovalCount: Int
    ) {
        switch connection {
        case .ready, .fallback(.ready): connectionTitle = "연결됨"
        case .replaying: connectionTitle = "상태 복원 중"
        case .connecting, .negotiating, .fallback: connectionTitle = "연결 중"
        case .failed: connectionTitle = "연결 실패"
        case .disconnected: connectionTitle = "연결 끊김"
        }
        var values = [DesktopMenuItem(
            title: "연결: \(connectionTitle)", destination: .connection
        )]
        if let sessionID {
            values.append(DesktopMenuItem(
                title: "업무: \(sessionID)", destination: .session(id: sessionID)
            ))
        }
        values.append(DesktopMenuItem(
            title: "승인 요청 \(max(0, pendingApprovalCount))건", destination: .approvals
        ))
        items = values
    }
}

public struct DesktopMenuView: View {
    public let model: DesktopMenuModel
    private let navigate: (DesktopMenuDestination) -> Void

    public init(
        model: DesktopMenuModel,
        navigate: @escaping (DesktopMenuDestination) -> Void
    ) {
        self.model = model
        self.navigate = navigate
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(model.items) { item in
                Button(item.title) { navigate(item.destination) }
                    .buttonStyle(.plain)
                    .accessibilityHint("Birkin의 승인 화면으로 이동하며 결정을 대신 내리지 않습니다")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityLabel("Birkin 상태 메뉴")
    }
}
