import BirkinNativeProtocol
import SwiftUI

public enum ProductSurfaceControl: Equatable, Sendable {
    case browserBack
    case browserForward
    case browserReload
    case browserNavigate
    case computerUseApproveOnce
    case computerUseReject
    case officeNew
    case officeOpen
}

public struct BrowserAsideView: View {
    public let presentation: BrowserAsidePresentation
    public let canNavigate: Bool
    public let back: () -> Void
    public let forward: () -> Void
    public let reload: () -> Void
    public let navigate: () -> Void

    public init(
        presentation: BrowserAsidePresentation,
        canNavigate: Bool,
        back: @escaping () -> Void = {},
        forward: @escaping () -> Void = {},
        reload: @escaping () -> Void = {},
        navigate: @escaping () -> Void = {}
    ) {
        self.presentation = presentation
        self.canNavigate = canNavigate
        self.back = back
        self.forward = forward
        self.reload = reload
        self.navigate = navigate
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Button(action: back) { Image(systemName: "chevron.backward") }
                    .accessibilityLabel("Browser back")
                Button(action: forward) { Image(systemName: "chevron.forward") }
                    .accessibilityLabel("Browser forward")
                Button(action: reload) { Image(systemName: "arrow.clockwise") }
                    .accessibilityLabel("Reload browser")
                Button("Navigate", action: navigate)
                    .accessibilityLabel("Navigate browser")
            }
            .disabled(!canNavigate)
            Text(presentation.displayURL.isEmpty ? "No page loaded" : presentation.displayURL)
                .lineLimit(1)
            Text("Private profile \(presentation.profileGeneration) · \(presentation.ownerKind) · frame \(presentation.frameRevision)")
                .font(.caption).foregroundStyle(.secondary)
            Group {
                if presentation.frameReference != nil {
                    Label("Redacted Python frame ready", systemImage: "rectangle.on.rectangle")
                } else {
                    Text("No frame available.")
                }
            }
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            if let refusal = presentation.refusal {
                Text(refusal).foregroundStyle(.red)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Browser Aside private workspace")
    }
}

public struct ComputerUseStatusView: View {
    public let presentation: ComputerUsePresentation
    public let canDecide: Bool
    public let approve: () -> Void
    public let reject: () -> Void

    public init(
        presentation: ComputerUsePresentation,
        canDecide: Bool,
        approve: @escaping () -> Void = {},
        reject: @escaping () -> Void = {}
    ) {
        self.presentation = presentation
        self.canDecide = canDecide
        self.approve = approve
        self.reject = reject
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(
                presentation.permissionPrompted ? "Permission status unavailable" : "Checked without prompting",
                systemImage: presentation.permissionPrompted ? "exclamationmark.triangle" : "checkmark.shield"
            )
            if let state = presentation.consentState {
                Text("One-shot consent: \(state)")
                if let app = presentation.applicationRef { Text("Application \(app)") }
                if let window = presentation.windowRef { Text("Window \(window)") }
                if let countdown = presentation.countdownText {
                    Text(countdown).monospacedDigit().accessibilityLabel("Consent expires in \(countdown)")
                }
                HStack {
                    Button("Approve once", action: approve)
                        .accessibilityLabel("Approve Computer Use once")
                    Button("Reject", action: reject)
                        .accessibilityLabel("Reject Computer Use")
                }
                .disabled(!canDecide || state != "proposed")
            } else {
                Text("No foreground consent requested.")
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Computer Use consent")
    }
}

public struct OfficeView: View {
    public let presentation: OfficePresentation
    public let canCreate: Bool
    public let canOpen: Bool
    public let create: () -> Void
    public let open: () -> Void

    public init(
        presentation: OfficePresentation,
        canCreate: Bool,
        canOpen: Bool,
        create: @escaping () -> Void = {},
        open: @escaping () -> Void = {}
    ) {
        self.presentation = presentation
        self.canCreate = canCreate
        self.canOpen = canOpen
        self.create = create
        self.open = open
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("Formats: \(presentation.formats.joined(separator: ", "))")
            HStack {
                Button("New", action: create)
                    .disabled(!canCreate)
                    .accessibilityLabel("Create jailed document")
                Button("Open", action: open)
                    .disabled(!canOpen)
                    .accessibilityLabel("Open jailed document")
            }
            Text("\(presentation.documents.count) jailed document(s) · \(presentation.receipts.count) receipt(s)")
                .font(.caption).foregroundStyle(.secondary)
            if let refusal = presentation.refusalCode {
                Label("Refused: \(refusal)", systemImage: "hand.raised.fill")
                    .foregroundStyle(.red)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Office document service")
    }
}
