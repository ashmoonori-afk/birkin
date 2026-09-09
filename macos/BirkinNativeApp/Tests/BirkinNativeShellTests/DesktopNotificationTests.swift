import Testing

@testable import BirkinNativeShell

@Suite("Bounded redacted desktop notifications")
struct DesktopNotificationTests {
    @Test("general notifications use bounded fixed copy and deep links only")
    func boundedDeepLinkOnly() {
        let seededSecret = "sk-seeded_PHASE11_SECRET_123456789"
        let command = "curl -H Authorization:Bearer_\(seededSecret) https://private.invalid"
        let payload = DesktopNotificationPayload(
            category: .sessionCompleted,
            itemID: "session-7",
            untrustedDetail: String(repeating: command, count: 20)
        )

        #expect(payload.title == "Birkin 업무가 완료되었습니다")
        #expect(payload.body == "Birkin에서 최종 결과를 확인하세요.")
        #expect(payload.body.utf8.count <= 120)
        #expect(!payload.body.contains(seededSecret))
        #expect(!payload.body.contains("curl"))
        #expect(payload.userInfo == ["route": "sessions", "item_id": "session-7"])
        #expect(payload.actions.isEmpty)
        #expect(!payload.userInfo.keys.contains("decision"))
    }

    @Test("approval notification discards untrusted command summary")
    func approvalRedaction() {
        let secret = "ghp_PHASE11_NOTIFICATION_SECRET"
        let payload = ApprovalNotificationPayload(
            approvalID: "approval-9",
            summary: "rm -rf / --token \(secret)"
        )

        #expect(payload.body == "Birkin에서 요청 내용을 확인하세요.")
        #expect(payload.body.utf8.count <= 120)
        #expect(!payload.body.contains(secret))
        #expect(!payload.body.contains("rm -rf"))
        #expect(payload.actions.isEmpty)
        #expect(payload.userInfo == [
            "route": "approvals", "approval_id": "approval-9",
        ])
    }

    @Test("failure notification cannot transport diagnostic detail")
    func diagnosticsStayOut() {
        let payload = DesktopNotificationPayload(
            category: .bridgeAttention,
            itemID: "bridge",
            untrustedDetail: "Authorization: Bearer secret full command text"
        )
        #expect(payload.title == "Birkin 확인이 필요합니다")
        #expect(payload.body == "Birkin에서 연결 세부 정보를 확인하세요.")
        #expect(payload.userInfo == ["route": "connection", "item_id": "bridge"])
        #expect(payload.actions.isEmpty)
    }
}
