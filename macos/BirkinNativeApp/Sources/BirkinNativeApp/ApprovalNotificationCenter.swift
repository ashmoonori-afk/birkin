import AppKit
import BirkinNativeShell
import UserNotifications

@MainActor
public protocol ApprovalNotificationScheduling: AnyObject {
    func prepare() async throws
    func schedule(_ payload: ApprovalNotificationPayload) async throws
}

@MainActor
final class MacOSApprovalNotificationCenter: NSObject,
    ApprovalNotificationScheduling,
    UNUserNotificationCenterDelegate
{
    static var isAvailable: Bool {
        Bundle.main.bundleURL.pathExtension == "app"
            && Bundle.main.bundleIdentifier != nil
    }

    private let center: UNUserNotificationCenter
    private let navigateToApprovals: @MainActor () -> Void
    private var authorized = false

    init(
        center: UNUserNotificationCenter = .current(),
        navigateToApprovals: @escaping @MainActor () -> Void
    ) {
        self.center = center
        self.navigateToApprovals = navigateToApprovals
        super.init()
        center.delegate = self
    }

    func prepare() async throws {
        let settings = await center.notificationSettings()
        authorized = settings.authorizationStatus == .authorized
            || settings.authorizationStatus == .provisional
    }

    func schedule(_ payload: ApprovalNotificationPayload) async throws {
        if !authorized {
            authorized = try await center.requestAuthorization(
                options: [.alert, .sound]
            )
        }
        guard authorized else {
            return
        }
        try await center.add(Self.request(for: payload))
    }

    static func request(
        for payload: ApprovalNotificationPayload
    ) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = payload.title
        content.body = payload.body
        content.userInfo = payload.userInfo
        let approvalID = payload.userInfo["approval_id"] ?? "unknown"
        return UNNotificationRequest(
            identifier: "approval:\(approvalID)",
            content: content,
            trigger: nil
        )
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        guard response.notification.request.content.userInfo["route"]
                as? String == "approvals"
        else {
            return
        }
        await MainActor.run {
            navigateToApprovals()
        }
    }
}
