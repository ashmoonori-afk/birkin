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
                Button("시작") { start?() }.disabled(start == nil || presentation.isLive)
                Button(action: { back?() }) { Image(systemName: "chevron.left") }
                    .disabled(back == nil || !presentation.canGoBack)
                    .accessibilityLabel("뒤로")
                Button(action: { forward?() }) { Image(systemName: "chevron.right") }
                    .disabled(forward == nil || !presentation.canGoForward)
                    .accessibilityLabel("앞으로")
                Button(action: { reload?() }) { Image(systemName: "arrow.clockwise") }
                    .disabled(reload == nil || !presentation.isLive)
                    .accessibilityLabel("새로고침")
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
            Text("전용 프로필 \(presentation.profileGeneration) · \(presentation.ownerKind) · 방문 기록 \(presentation.historyIndex + 1)/\(presentation.historyEntries.count)")
                .font(.caption).foregroundStyle(.secondary)
            Group {
                if let digest = presentation.frameDigest,
                   presentation.frameMediaType == "image/png",
                   presentation.frameMaximumBytes > 0 {
                    VStack {
                        Label("제한된 브라우저 화면", systemImage: "photo")
                        Text(digest).font(.caption2).lineLimit(1)
                        Text("버전 \(presentation.frameRevision) · 최대 \(presentation.frameMaximumBytes)바이트")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                } else { Text("표시할 화면이 없습니다.") }
            }
            .frame(maxWidth: .infinity, minHeight: 90)
            .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            if let refusal = presentation.refusal { Text(refusal).foregroundStyle(.red) }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("브라우저 전용 작업공간")
    }
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

    public var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(
                presentation.permissionPrompted ? "권한 상태를 확인할 수 없음" : "추가 요청 없이 확인됨",
                systemImage: presentation.permissionPrompted ? "exclamationmark.triangle" : "checkmark.shield"
            )
            Text("손쉬운 사용: \(presentation.accessibilityStatus) · 화면 기록: \(presentation.screenRecordingStatus)")
            Text("실행 환경: \(presentation.backendStatus) · 연결: \(presentation.bindingStatus)")
            if let state = presentation.consentState {
                Text("일회성 승인 \(presentation.grantID ?? "없음"): \(state)")
                if let action = presentation.action { Text("작업 \(action)") }
                if let app = presentation.applicationRef { Text("앱 \(app)") }
                if let window = presentation.windowRef { Text("창 \(window)") }
                if let countdown = presentation.countdownText { Text(countdown).monospacedDigit() }
                HStack {
                    Button("한 번만 승인", action: approve)
                    Button("거부", action: reject)
                    Button("한 번 실행", action: execute)
                        .disabled(!canExecute || state != "approved")
                }
                .disabled(!canDecide || state == "expired" || state == "consumed")
            } else { Text("확인이 필요한 화면 작업이 없습니다.").foregroundStyle(.secondary) }
            Text("실행 기록 \(presentation.receipts.count)건")
                .font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("컴퓨터 사용 승인")
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
            Picker("형식", selection: $format) {
                ForEach(presentation.formats, id: \.self) { Text($0).tag($0) }
            }
            TextField("문서 이름", text: $outputName).textFieldStyle(.roundedBorder)
            TextField("문서 내용", text: $content).textFieldStyle(.roundedBorder)
            HStack {
                Button("새 문서", action: createDocument)
                    .disabled(!canCreate || outputName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("열기", action: open)
                    .disabled(!canOpen || presentation.selectedDocument == nil)
            }
            Picker("문서", selection: Binding(
                get: { presentation.selectedArtifactID ?? "" },
                set: { if !$0.isEmpty { select($0) } }
            )) {
                Text("문서를 선택하세요").tag("")
                ForEach(presentation.documentPresentations) { Text($0.id).tag($0.id) }
            }
            if let document = presentation.selectedDocument {
                Text("활성 콘텐츠: \(document.activeContent.count) · 출처 \(document.provenance == nil ? "없음" : "확인됨") · 변환 \(document.conversion == nil ? "없음" : "기록됨")")
                    .font(.caption)
            }
            Text("보호된 문서 \(presentation.documents.count)개 · 작업 기록 \(presentation.receipts.count)건")
                .font(.caption).foregroundStyle(.secondary)
            if let refusal = presentation.refusalCode {
                Label("거부됨: \(refusal)", systemImage: "hand.raised.fill").foregroundStyle(.red)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("업무 문서 서비스")
    }
}
