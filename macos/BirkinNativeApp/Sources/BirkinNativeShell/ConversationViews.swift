import AppKit
import BirkinNativeProtocol
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
        .accessibilityLabel("Conversation message stream")
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
                            ? "Assistant response streaming" : "Tool running")
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
