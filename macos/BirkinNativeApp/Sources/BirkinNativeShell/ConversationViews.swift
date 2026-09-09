import AppKit
import BirkinNativeProtocol
import Foundation
import SwiftUI

public struct MessageStreamView: View {
    private let model: MessageStreamModel

    public init(projection: NativeProjectionState) {
        model = MessageStreamModel(projection: projection)
    }

    public var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                messageRows
            }
        }
        .accessibilityLabel("대화 메시지 목록")
    }

    @ViewBuilder
    private var messageRows: some View {
        ForEach(model.rows) { row in
            VStack(alignment: .leading, spacing: 4) {
                Label(row.title, systemImage: icon(row.kind))
                    .font(.caption.bold()).foregroundStyle(.secondary)
                Text(row.text).textSelection(.enabled)
                ForEach(row.attachments, id: \.importID) { attachment in
                    ImportedReferenceChip(reference: attachment)
                }
                if row.state == .streaming || row.state == .running {
                    ProgressView().controlSize(.small)
                        .accessibilityLabel(row.state == .streaming
                            ? "답변 작성 중" : "도구 실행 중")
                }
                if let failure = row.failure {
                    Text(failure.message).font(.caption).foregroundStyle(.red)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    private func icon(_ kind: ConversationRowKind) -> String {
        switch kind {
        case .user: "person"
        case .assistant: "sparkles"
        case .tool: "hammer"
        case .approval: "checkmark.shield"
        case .question: "questionmark.circle"
        case .receipt: "checkmark.seal"
        case .failure: "xmark.octagon"
        case .interrupted: "pause.circle"
        }
    }
}

public struct ConversationComposerView: View {
    @ObservedObject private var model: ConversationComposerModel
    private let isSendEnabled: Bool
    private let send: () -> Void

    public init(
        model: ConversationComposerModel,
        isSendEnabled: Bool,
        send: @escaping () -> Void
    ) {
        self.model = model
        self.isSendEnabled = isSendEnabled
        self.send = send
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(
                NativeLocalization.string("Code mode"),
                isOn: $model.isCodeMode
            )
                .accessibilityLabel(NativeLocalization.string("Code mode"))
            IMEAwareTextEditor(text: $model.draft, send: send)
                .frame(minHeight: 72)
            .font(model.isCodeMode ? .system(.body, design: .monospaced) : .body)
            .accessibilityLabel(NativeLocalization.string(
                model.isCodeMode ? "Code message draft" : "Message draft"
            ))
            ForEach(model.attachments, id: \.importID) { attachment in
                ImportedReferenceChip(reference: attachment)
            }
            HStack {
                Text(NativeLocalization.string(
                    "%lld bytes",
                    Int64(model.draftByteCount)
                ))
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                Spacer()
                Button(NativeLocalization.string("Send"), action: send)
                    .keyboardShortcut(.return, modifiers: .command)
                    .accessibilityLabel(NativeLocalization.string(
                        "Send message"
                    ))
                    .disabled(!isSendEnabled)
            }
            if let reason = model.visibleReason {
                Text(reason).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

public struct ResearchReportView: View {
    private let rows: [ConversationRow]

    public init(projection: NativeProjectionState) {
        rows = ConversationRows.parse(projection: projection).filter {
            $0.kind == .assistant
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("리서치 보고서").font(.title2.weight(.bold))
                    Text("결론, 근거와 미해결 항목을 원문 흐름대로 표시합니다.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                if rows.last?.state == .streaming {
                    ProgressView("조사 중")
                }
            }
            if let report = rows.last {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(Self.blocks(report.text).enumerated()), id: \.offset) { _, block in
                        switch block {
                        case .heading(let level, let text):
                            Text(Self.safeMarkdown(text))
                                .font(level == 1 ? .title2.weight(.bold) : .headline)
                        case .bullet(let text):
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text("•")
                                Text(Self.safeMarkdown(text))
                            }
                        case .code(let text):
                            Text(text).font(.system(.body, design: .monospaced))
                                .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                                .background(.secondary.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                        case .paragraph(let text):
                            Text(Self.safeMarkdown(text)).font(.body).lineSpacing(5)
                        }
                    }
                }
                    .textSelection(.enabled)
                    .environment(\.openURL, OpenURLAction { url in
                        guard ["http", "https"].contains(url.scheme?.lowercased() ?? "")
                        else { return .discarded }
                        return .systemAction(url)
                    })
                    .accessibilityLabel("리서치 결과")
            } else {
                VStack(spacing: 8) {
                    Label("아직 리서치 결과가 없습니다", systemImage: "doc.text.magnifyingglass")
                        .font(.headline)
                    Text("왼쪽에서 리서치 업무를 시작하고 주제를 보내세요.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 180)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    public static func safeMarkdown(_ source: String) -> AttributedString {
        let sanitized = sanitizedMarkdownSource(source)
        return (try? AttributedString(
            markdown: sanitized,
            options: .init(interpretedSyntax: .full)
        )) ?? AttributedString(sanitized)
    }

    public static func sanitizedMarkdownSource(_ source: String) -> String {
        let pattern = #"\]\((?!https?://)[^)]+\)"#
        let range = NSRange(source.startIndex..., in: source)
        return (try? NSRegularExpression(
            pattern: pattern, options: [.caseInsensitive]
        ).stringByReplacingMatches(
            in: source, range: range, withTemplate: "]"
        )) ?? source
    }

    enum ReportBlock: Equatable {
        case heading(Int, String)
        case bullet(String)
        case code(String)
        case paragraph(String)
    }

    static func blocks(_ source: String) -> [ReportBlock] {
        var result: [ReportBlock] = []
        var code: [Substring] = []
        var inCode = false
        for line in source.split(separator: "\n", omittingEmptySubsequences: false) {
            if line.hasPrefix("```") {
                if inCode {
                    result.append(.code(code.joined(separator: "\n")))
                    code.removeAll()
                }
                inCode.toggle()
            } else if inCode {
                code.append(line)
            } else if line.hasPrefix("## ") {
                result.append(.heading(2, String(line.dropFirst(3))))
            } else if line.hasPrefix("# ") {
                result.append(.heading(1, String(line.dropFirst(2))))
            } else if line.hasPrefix("- ") {
                result.append(.bullet(String(line.dropFirst(2))))
            } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                result.append(.paragraph(String(line)))
            }
        }
        if !code.isEmpty { result.append(.code(code.joined(separator: "\n"))) }
        return result
    }
}

private struct IMEAwareTextEditor: NSViewRepresentable {
    @Binding var text: String
    let send: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        let view = NSTextView()
        view.delegate = context.coordinator
        view.isRichText = false
        view.isAutomaticQuoteSubstitutionEnabled = false
        view.string = text
        scroll.documentView = view
        scroll.hasVerticalScroller = true
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView else { return }
        if view.string != text { view.string = text }
        context.coordinator.parent = self
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: IMEAwareTextEditor
        init(parent: IMEAwareTextEditor) { self.parent = parent }

        func textDidChange(_ notification: Notification) {
            guard let view = notification.object as? NSTextView else { return }
            parent.text = view.string
        }

        func textView(_ textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
            let shouldSend = SendKeyPolicy.shouldSend(
                commandPressed: NSApp.currentEvent?.modifierFlags.contains(.command) == true,
                returnPressed: commandSelector == #selector(NSResponder.insertNewline(_:)),
                hasMarkedText: textView.hasMarkedText()
            )
            if shouldSend { parent.send() }
            return shouldSend
        }
    }
}
