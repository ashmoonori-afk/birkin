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
        pendingApprovalCount: Int,
        locale: Locale = NativeLocalization.currentLocale
    ) {
        func text(_ key: String) -> String {
            NativeLocalization.string(key, locale: locale)
        }
        switch connection {
        case .ready, .fallback(.ready): connectionTitle = text("Connected")
        case .replaying: connectionTitle = text("Replaying")
        case .connecting, .negotiating, .fallback:
            connectionTitle = text("Connecting")
        case .failed: connectionTitle = text("Connection failed")
        case .disconnected: connectionTitle = text("Disconnected")
        }
        var values = [DesktopMenuItem(
            title: NativeLocalization.string(
                "Connection: %@",
                locale: locale,
                connectionTitle
            ),
            destination: .connection
        )]
        if let sessionID {
            values.append(DesktopMenuItem(
                title: NativeLocalization.string(
                    "Session: %@",
                    locale: locale,
                    sessionID
                ),
                destination: .session(id: sessionID)
            ))
        }
        values.append(DesktopMenuItem(
            title: NativeLocalization.string(
                "Approvals (%lld)",
                locale: locale,
                Int64(max(0, pendingApprovalCount))
            ),
            destination: .approvals
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
                    .accessibilityHint(NativeLocalization.string(
                        "Navigates in Birkin; does not make a decision"
                    ))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityLabel(NativeLocalization.string("Birkin status menu"))
    }
}
