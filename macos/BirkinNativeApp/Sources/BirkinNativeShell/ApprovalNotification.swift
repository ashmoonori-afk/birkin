/// A notification is navigation only. It cannot encode or submit a decision.
public struct ApprovalNotificationPayload: Equatable, Sendable {
    public let title: String
    public let body: String
    public let userInfo: [String: String]
    public let actions: [String]

    public init(approvalID: String, summary _: String) {
        title = "Approval requested"
        body = "Open Birkin to review this request."
        userInfo = ["route": "approvals", "approval_id": approvalID]
        actions = []
    }
}

public enum DesktopNotificationCategory: Equatable, Sendable {
    case sessionCompleted
    case bridgeAttention
}

/// Fixed-copy notification projection. Canonical content and diagnostics stay in-app.
public struct DesktopNotificationPayload: Equatable, Sendable {
    public let title: String
    public let body: String
    public let userInfo: [String: String]
    public let actions: [String]

    public init(
        category: DesktopNotificationCategory,
        itemID: String,
        untrustedDetail _: String
    ) {
        switch category {
        case .sessionCompleted:
            title = "Birkin session completed"
            body = "Open Birkin to review the canonical result."
            userInfo = ["route": "sessions", "item_id": itemID]
        case .bridgeAttention:
            title = "Birkin needs attention"
            body = "Open Birkin to view bounded diagnostics."
            userInfo = ["route": "connection", "item_id": itemID]
        }
        actions = []
    }
}
