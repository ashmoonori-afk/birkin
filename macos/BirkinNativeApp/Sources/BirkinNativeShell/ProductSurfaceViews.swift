import BirkinNativeProtocol
import SwiftUI

public enum ProductSurfaceControl: Equatable, Sendable {
    case browserStart
    case browserNavigate(url: String)
    case computerUseApproveOnce
    case computerUseReject
    case officeNew
    case officeOpen

    public static let browserCommandTypes = [
        "browser.start", "browser.navigate", "browser.back", "browser.forward",
        "browser.reload", "browser.close",
    ]
}

public struct BrowserAsideView: View {
    public let presentation: BrowserAsidePresentation
    public let start: (() -> Void)?
    public let navigate: ((String) -> Void)?
    public let back: (() -> Void)?
    public let forward: (() -> Void)?
    public let reload: (() -> Void)?
    public let close: (() -> Void)?
    @State private var address = ""

    public init(
        presentation: BrowserAsidePresentation,
        start: (() -> Void)? = nil,
        navigate: ((String) -> Void)? = nil,
        back: (() -> Void)? = nil,
        forward: (() -> Void)? = nil,
        reload: (() -> Void)? = nil,
        close: (() -> Void)? = nil
    ) {
        self.presentation = presentation
        self.start = start; self.navigate = navigate; self.back = back
        self.forward = forward; self.reload = reload; self.close = close
    }

    private func submit() {
        let value = address.trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty { navigate?(value) }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Button("Start") { start?() }.disabled(start == nil || presentation.isLive)
                Button(action: { back?() }) { Image(systemName: "chevron.left") }
                    .disabled(back == nil || !presentation.canGoBack)
                    .accessibilityLabel("Back")
                Button(action: { forward?() }) { Image(systemName: "chevron.right") }
                    .disabled(forward == nil || !presentation.canGoForward)
                    .accessibilityLabel("Forward")
                Button(action: { reload?() }) { Image(systemName: "arrow.clockwise") }
                    .disabled(reload == nil || !presentation.isLive)
                    .accessibilityLabel("Reload")
                Button("Close") { close?() }.disabled(close == nil || !presentation.isLive)
            }
            HStack {
                TextField("Address", text: $address).textFieldStyle(.roundedBorder)
                    .onSubmit { submit() }.accessibilityLabel("Browser address")
                Button("Navigate", action: submit)
                    .disabled(navigate == nil || !presentation.isLive || address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if presentation.isLoading { ProgressView("Loading") }
            Text(presentation.displayURL.isEmpty ? "No page loaded" : presentation.displayURL).lineLimit(1)
            Text("Private profile \(presentation.profileGeneration) · \(presentation.ownerKind) · history \(presentation.historyIndex + 1)/\(presentation.historyEntries.count)")
                .font(.caption).foregroundStyle(.secondary)
            Group {
                if let digest = presentation.frameDigest,
                   presentation.frameMediaType == "image/png",
                   presentation.frameMaximumBytes > 0 {
                    VStack {
                        Label("Bounded browser frame", systemImage: "photo")
                        Text(digest).font(.caption2).lineLimit(1)
                        Text("revision \(presentation.frameRevision) · limit \(presentation.frameMaximumBytes) bytes")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                } else { Text("No frame available.") }
            }
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            if let refusal = presentation.refusal { Text(refusal).foregroundStyle(.red) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Browser Aside private workspace")
    }
}

public enum ComputerUseGuidanceSemanticRole: String, Equatable, Sendable {
    case staticText
}

public struct ComputerUseGuidanceSemantic: Equatable, Identifiable, Sendable {
    public let id: String
    public let role: ComputerUseGuidanceSemanticRole
    public let settingsPath: String
    public let responsibleProcess: String
    public let actions: [String]
}

public struct ComputerUseStatusView: View {
    public let presentation: ComputerUsePresentation
    public let canDecide: Bool
    public let canExecute: Bool
    public let approve: () -> Void
    public let reject: () -> Void
    public let execute: () -> Void

    public init(
        presentation: ComputerUsePresentation,
        canDecide: Bool,
        canExecute: Bool = false,
        approve: @escaping () -> Void = {},
        reject: @escaping () -> Void = {},
        execute: @escaping () -> Void = {}
    ) {
        self.presentation = presentation; self.canDecide = canDecide; self.canExecute = canExecute
        self.approve = approve; self.reject = reject; self.execute = execute
    }

    public var guidanceSemantics: [ComputerUseGuidanceSemantic] {
        presentation.guidance.map {
            ComputerUseGuidanceSemantic(
                id: "computer-use.guidance.\($0.id)",
                role: .staticText,
                settingsPath: $0.settingsPath,
                responsibleProcess: $0.responsibleProcess,
                actions: []
            )
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(
                presentation.permissionPrompted ? "Permission status unavailable" : "Checked without prompting",
                systemImage: presentation.permissionPrompted ? "exclamationmark.triangle" : "checkmark.shield"
            )
            Text("Accessibility: \(presentation.accessibilityStatus) · Screen Recording: \(presentation.screenRecordingStatus)")
            Text("Backend: \(presentation.backendStatus) · Binding: \(presentation.bindingStatus)")
            ForEach(guidanceSemantics) { guidance in
                VStack(alignment: .leading, spacing: 4) {
                    Text(guidance.responsibleProcess)
                    Text(guidance.settingsPath)
                }
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(guidance.id)
            }
            if let state = presentation.consentState {
                Text("One-shot grant \(presentation.grantID ?? "missing"): \(state)")
                if let action = presentation.action { Text("Action \(action)") }
                if let app = presentation.applicationRef { Text("Application \(app)") }
                if let window = presentation.windowRef { Text("Window \(window)") }
                if let countdown = presentation.countdownText { Text(countdown).monospacedDigit() }
                HStack {
                    Button("Approve once", action: approve)
                    Button("Reject", action: reject)
                    Button("Execute once", action: execute)
                        .disabled(!canExecute || state != "approved")
                }
                .disabled(!canDecide || state == "expired" || state == "consumed")
            } else { Text("No foreground consent requested.").foregroundStyle(.secondary) }
            Text("\(presentation.receipts.count) execution receipt(s)")
                .font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Computer Use consent")
    }
}

public struct OfficeView: View {
    public let presentation: OfficePresentation
    public let canCreate: Bool
    public let canOpen: Bool
    public let createForm: (OfficeFormState) -> Void
    public let open: () -> Void
    public let select: (String) -> Void
    @State private var format: String
    @State private var outputName: String
    @State private var content: String

    public init(
        presentation: OfficePresentation,
        canCreate: Bool,
        canOpen: Bool,
        createForm: @escaping (OfficeFormState) -> Void = { _ in },
        open: @escaping () -> Void = {},
        select: @escaping (String) -> Void = { _ in }
    ) {
        self.presentation = presentation; self.canCreate = canCreate; self.canOpen = canOpen
        self.createForm = createForm; self.open = open; self.select = select
        _format = State(initialValue: presentation.form.format)
        _outputName = State(initialValue: presentation.form.outputName)
        _content = State(initialValue: "")
    }

    public init(
        presentation: OfficePresentation, canCreate: Bool, canOpen: Bool,
        create: @escaping () -> Void, open: @escaping () -> Void
    ) {
        self.init(
            presentation: presentation, canCreate: canCreate, canOpen: canOpen,
            createForm: { _ in create() }, open: open
        )
    }

    private func createDocument() {
        createForm(OfficeFormState(
            format: format, outputName: outputName,
            content: ["paragraphs": .array([.string(content)])]
        ))
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Picker("Format", selection: $format) {
                ForEach(presentation.formats, id: \.self) { Text($0).tag($0) }
            }
            TextField("Document name", text: $outputName).textFieldStyle(.roundedBorder)
            TextField("Document content", text: $content).textFieldStyle(.roundedBorder)
            HStack {
                Button("New", action: createDocument)
                    .disabled(!canCreate || outputName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Open", action: open)
                    .disabled(!canOpen || presentation.selectedDocument == nil)
            }
            Picker("Document", selection: Binding(
                get: { presentation.selectedArtifactID ?? "" },
                set: { if !$0.isEmpty { select($0) } }
            )) {
                Text("Select a document").tag("")
                ForEach(presentation.documentPresentations) { Text($0.id).tag($0.id) }
            }
            if let document = presentation.selectedDocument {
                Text("Active content: \(document.activeContent.count) · provenance \(document.provenance == nil ? "missing" : "verified") · conversion \(document.conversion == nil ? "none" : "recorded")")
                    .font(.caption)
            }
            Text("\(presentation.documents.count) jailed document(s) · \(presentation.receipts.count) receipt(s)")
                .font(.caption).foregroundStyle(.secondary)
            if let refusal = presentation.refusalCode {
                Label("Refused: \(refusal)", systemImage: "hand.raised.fill").foregroundStyle(.red)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Office document service")
    }
}
