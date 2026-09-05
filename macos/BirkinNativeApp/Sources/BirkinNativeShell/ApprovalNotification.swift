/// A notification is navigation only. It cannot encode or submit a decision.
public struct ApprovalNotificationPayload: Equatable, Sendable {
    public let title: String
    public let body: String
    public let userInfo: [String: String]
    public let actions: [String]

    public init(approvalID: String, summary _: String) {
        title = "승인 요청이 도착했습니다"
        body = "Birkin에서 요청 내용을 확인하세요."
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
            title = "Birkin 업무가 완료되었습니다"
            body = "Birkin에서 최종 결과를 확인하세요."
            userInfo = ["route": "sessions", "item_id": itemID]
        case .bridgeAttention:
            title = "Birkin 확인이 필요합니다"
            body = "Birkin에서 연결 세부 정보를 확인하세요."
            userInfo = ["route": "connection", "item_id": itemID]
        }
        actions = []
    }
}
