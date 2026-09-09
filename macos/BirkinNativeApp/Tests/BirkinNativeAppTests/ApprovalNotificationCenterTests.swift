import Testing
import UserNotifications

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@MainActor
private final class RecordingApprovalNotifications: ApprovalNotificationScheduling {
    var payloads: [ApprovalNotificationPayload] = []

    func prepare() async throws {}

    func schedule(_ payload: ApprovalNotificationPayload) async throws {
        payloads.append(payload)
    }
}

@Suite("macOS approval notification center")
struct ApprovalNotificationCenterTests {
    @MainActor
    @Test("request carries fixed copy and navigation metadata without an action category")
    func navigationOnlyRequest() {
        let request = MacOSApprovalNotificationCenter.request(
            for: ApprovalNotificationPayload(
                approvalID: "approval-1",
                summary: "UNTRUSTED summary"
            )
        )
        let content = request.content

        #expect(request.identifier == "approval:approval-1")
        #expect(content.title == "승인 요청이 도착했습니다")
        #expect(content.body == "Birkin에서 요청 내용을 확인하세요.")
        #expect(content.categoryIdentifier.isEmpty)
        #expect(content.userInfo["route"] as? String == "approvals")
        #expect(content.userInfo["approval_id"] as? String == "approval-1")
    }

    @MainActor
    @Test("runtime schedules each canonical approval once")
    func runtimeDeduplicatesApprovalEvents() async throws {
        let notifications = RecordingApprovalNotifications()
        let runtime = BirkinApplicationRuntime(
            socketPath: "/private/tmp/not-used",
            ownedBridge: nil,
            approvalNotifications: notifications
        )
        let event = NativeEnvelope(
            kind: .event,
            id: "approval-event-1",
            body: [
                "type": .string("approval.requested"),
                "payload": .object([
                    "approval_id": .string("approval-1"),
                    "summary": .string("UNTRUSTED secret"),
                ]),
            ]
        )

        try await runtime.processApprovalNotification(event)
        try await runtime.processApprovalNotification(event)

        #expect(notifications.payloads.count == 1)
        #expect(notifications.payloads[0].userInfo == [
            "route": "approvals",
            "approval_id": "approval-1",
        ])
        #expect(!notifications.payloads[0].body.contains("UNTRUSTED secret"))
    }

    @MainActor
    @Test("notification navigation focuses only the approvals section")
    func notificationNavigation() {
        let runtime = BirkinApplicationRuntime(
            socketPath: "/private/tmp/not-used",
            ownedBridge: nil,
            approvalNotifications: RecordingApprovalNotifications()
        )

        runtime.navigateToApprovals()

        #expect(runtime.presentationModel.target == .section(.approvals))
    }
}
