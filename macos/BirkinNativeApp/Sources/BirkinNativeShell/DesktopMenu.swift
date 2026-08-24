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
        case .ready, .fallback(.ready): connectionTitle = "Connected"
        case .replaying: connectionTitle = "Replaying"
        case .connecting, .negotiating, .fallback: connectionTitle = "Connecting"
        case .failed: connectionTitle = "Connection failed"
        case .disconnected: connectionTitle = "Disconnected"
        }
        var values = [DesktopMenuItem(
            title: "Connection: \(connectionTitle)", destination: .connection
        )]
        if let sessionID {
            values.append(DesktopMenuItem(
                title: "Session: \(sessionID)", destination: .session(id: sessionID)
            ))
        }
        values.append(DesktopMenuItem(
            title: "Approvals (\(max(0, pendingApprovalCount)))", destination: .approvals
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
                    .accessibilityHint("Navigates in Birkin; does not make a decision")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityLabel("Birkin status menu")
    }
}
