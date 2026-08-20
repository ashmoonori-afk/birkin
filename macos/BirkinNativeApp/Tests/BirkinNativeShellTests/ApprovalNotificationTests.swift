import Testing

@testable import BirkinNativeShell

@Suite("Approval notification non-authority")
struct ApprovalNotificationTests {
    @Test("notification payload only deep-links to the approval surface")
    func deepLinkOnly() {
        let payload = ApprovalNotificationPayload(
            approvalID: "approval-1", summary: "Review shell access"
        )

        #expect(payload.userInfo == [
            "route": "approvals", "approval_id": "approval-1",
        ])
        #expect(payload.actions.isEmpty)
        #expect(!payload.userInfo.keys.contains("decision"))
        #expect(!payload.userInfo.values.contains("approve"))
        #expect(!payload.userInfo.values.contains("reject"))
    }
}
