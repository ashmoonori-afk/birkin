/// A notification is navigation only. It cannot encode or submit a decision.
public struct ApprovalNotificationPayload: Equatable, Sendable {
    public let title: String
    public let body: String
    public let userInfo: [String: String]
    public let actions: [String]

    public init(approvalID: String, summary: String) {
        title = "Approval requested"
        body = summary
        userInfo = ["route": "approvals", "approval_id": approvalID]
        actions = []
    }
}
