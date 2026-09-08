import AppKit
import BirkinNativeProtocol
import SwiftUI

public enum ProductSurfaceControl: Equatable, Sendable {
    case browserStart
    case browserNavigate(url: String)
    case computerUseAnswer(decision: String)
    case computerUseExecute
    case officeCreate(form: OfficeFormState)
    case officeSelect(artifactID: String)
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
                Button("시작") { start?() }.disabled(start == nil || presentation.isLive)
                Button(action: { back?() }) { Image(systemName: "chevron.left") }
                    .disabled(back == nil || !presentation.canGoBack)
                    .accessibilityLabel("뒤로")
                Button(action: { forward?() }) { Image(systemName: "chevron.right") }
                    .disabled(forward == nil || !presentation.canGoForward)
                    .accessibilityLabel("앞으로")
                Button(action: { reload?() }) { Image(systemName: "arrow.clockwise") }
                    .disabled(reload == nil || !presentation.isLive)
                    .accessibilityLabel("새로 고침")
                Button("닫기") { close?() }.disabled(close == nil || !presentation.isLive)
            }
            HStack {
                TextField("주소", text: $address).textFieldStyle(.roundedBorder)
                    .onSubmit { submit() }.accessibilityLabel("브라우저 주소")
                Button("이동", action: submit)
                    .disabled(navigate == nil || !presentation.isLive || address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if presentation.isLoading { ProgressView("불러오는 중") }
            Text(presentation.displayURL.isEmpty ? "열린 페이지가 없습니다" : presentation.displayURL).lineLimit(1)
            Text("비공개 프로필 \(presentation.profileGeneration) · 소유자 \(presentation.ownerKind) · 기록 \(presentation.historyIndex + 1)/\(presentation.historyEntries.count)")
                .font(.caption).foregroundStyle(.secondary)
            Group {
                if let digest = presentation.frameDigest,
                   presentation.frameMediaType == "image/png",
                   presentation.frameMaximumBytes > 0 {
                    VStack {
                        Label("브라우저 화면 근거", systemImage: "photo")
                        Text(digest).font(.caption2).lineLimit(1)
                        Text("리비전 \(presentation.frameRevision) · 한도 \(presentation.frameMaximumBytes)바이트")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                } else { Text("확인할 수 있는 화면 근거가 없습니다.") }
            }
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            if let refusal = presentation.refusal { Text(refusal).foregroundStyle(.red) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("리서치용 비공개 브라우저")
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
                presentation.permissionPrompted ? "권한 상태를 확인할 수 없습니다" : "권한 요청 없이 확인함",
                systemImage: presentation.permissionPrompted ? "exclamationmark.triangle" : "checkmark.shield"
            )
            Text("손쉬운 사용: \(presentation.accessibilityStatus) · 화면 기록: \(presentation.screenRecordingStatus)")
            Text("백엔드: \(presentation.backendStatus) · 연결: \(presentation.bindingStatus)")
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
                Text("일회성 권한 \(presentation.grantID ?? "확인 필요"): \(state)")
                if let action = presentation.action { Text("작업 \(action)") }
                if let app = presentation.applicationRef { Text("앱 \(app)") }
                if let window = presentation.windowRef { Text("창 \(window)") }
                if let countdown = presentation.countdownText { Text(countdown).monospacedDigit() }
                HStack {
                    Button("한 번 승인", action: approve)
                        .disabled(!canDecide || state != "proposed")
                    Button("거부", action: reject)
                        .disabled(!canDecide || state != "proposed")
                    Button("한 번 실행", action: execute)
                        .disabled(!canExecute || state != "approved")
                }
            } else { Text("요청된 화면 작업 승인이 없습니다.").foregroundStyle(.secondary) }
            Text("실행 영수증 \(presentation.receipts.count)개")
                .font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("화면 작업 승인")
    }
}

public struct OfficeView: View {
    public let presentation: OfficePresentation
    public let canCreate: Bool
    public let canOpen: Bool
    public let canSelect: Bool
    public let createForm: (OfficeFormState) -> Void
    public let open: () -> Void
    public let select: (String) -> Void
    @Binding private var format: String
    @Binding private var outputName: String
    @Binding private var content: String

    public init(
        presentation: OfficePresentation,
        canCreate: Bool,
        canOpen: Bool,
        canSelect: Bool = false,
        format: Binding<String>? = nil,
        outputName: Binding<String>? = nil,
        content: Binding<String>? = nil,
        createForm: @escaping (OfficeFormState) -> Void = { _ in },
        open: @escaping () -> Void = {},
        select: @escaping (String) -> Void = { _ in }
    ) {
        self.presentation = presentation; self.canCreate = canCreate; self.canOpen = canOpen
        self.canSelect = canSelect
        self.createForm = createForm; self.open = open; self.select = select
        _format = format ?? .constant(presentation.form.format)
        _outputName = outputName ?? .constant(presentation.form.outputName)
        _content = content ?? .constant("")
    }

    public init(
        presentation: OfficePresentation, canCreate: Bool, canOpen: Bool,
        create: @escaping () -> Void, open: @escaping () -> Void
    ) {
        self.init(
            presentation: presentation, canCreate: canCreate, canOpen: canOpen,
            canSelect: false,
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
        VStack(alignment: .leading, spacing: 12) {
            Text("새 문서")
                .font(.title3.weight(.semibold))
            Text("작성한 내용은 검토와 승인을 거쳐 저장됩니다.")
                .font(.subheadline).foregroundStyle(.secondary)
            Picker("파일 형식", selection: $format) {
                ForEach(presentation.formats, id: \.self) { Text($0).tag($0) }
            }
            TextField("문서 이름", text: $outputName).textFieldStyle(.roundedBorder)
            TextEditor(text: $content)
                .frame(minHeight: 96)
                .padding(6)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
                .overlay { RoundedRectangle(cornerRadius: 10).stroke(Color(red: 0.84, green: 0.87, blue: 0.90)) }
                .accessibilityLabel("문서 내용")
            HStack {
                Button("검토 요청", action: createDocument)
                    .buttonStyle(.borderedProminent)
                    .tint(Color(red: 0.07, green: 0.42, blue: 0.38))
                    .disabled(!canCreate || outputName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("선택한 문서 열기", action: open)
                    .disabled(!canOpen || presentation.selectedDocument == nil)
            }
            Divider()
            Text("문서 보관함").font(.headline)
            Picker("문서", selection: Binding(
                get: { presentation.selectedArtifactID ?? "" },
                set: { if canSelect && !$0.isEmpty { select($0) } }
            )) {
                Text("문서를 선택하세요").tag("")
                ForEach(presentation.documentPresentations) { Text($0.id).tag($0.id) }
            }
            .disabled(!canSelect)
            if let document = presentation.selectedDocument {
                Text("내용 \(document.activeContent.count)개 · 출처 \(document.provenance == nil ? "확인 필요" : "확인됨") · 변환 \(document.conversion == nil ? "없음" : "기록됨")")
                    .font(.caption)
            }
            Text("격리 문서 \(presentation.documents.count)개 · 영수증 \(presentation.receipts.count)개")
                .font(.caption).foregroundStyle(.secondary)
            if let refusal = presentation.refusalCode {
                Label("요청이 거부되었습니다: \(refusal)", systemImage: "hand.raised.fill").foregroundStyle(.red)
            }
            if !canCreate && !canOpen && !canSelect {
                Label("현재 연결에서는 문서 작업을 사용할 수 없습니다.", systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Office 문서 작업")
    }
}
