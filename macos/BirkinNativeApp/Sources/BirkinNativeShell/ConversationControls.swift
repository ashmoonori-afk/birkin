import AppKit
import BirkinNativeProtocol
import SwiftUI

public enum ConversationRole: Equatable, Sendable {
    case user
    case assistant
}

public enum ConversationMessageState: Equatable, Sendable {
    case complete
    case streaming
}

public struct ConversationMessage: Equatable, Identifiable, Sendable {
    public let id: String
    public let role: ConversationRole
    public let text: String
    public let state: ConversationMessageState
}

public struct MessageStreamModel: Equatable, Sendable {
    public let messages: [ConversationMessage]

    public init(projection: NativeProjectionState) {
        messages = projection.conversation.compactMap { raw in
            guard case .string(let id) = raw["id"],
                  case .string(let kind) = raw["kind"],
                  case .string(let text) = raw["text"] else { return nil }
            switch kind {
            case "user_message":
                return ConversationMessage(id: id, role: .user, text: text, state: .complete)
            case "assistant_stream":
                return ConversationMessage(id: id, role: .assistant, text: text, state: .streaming)
            case "assistant_message":
                return ConversationMessage(id: id, role: .assistant, text: text, state: .complete)
            default:
                return nil
            }
        }
    }
}

public struct MessageStreamView: View {
    private let model: MessageStreamModel

    public init(projection: NativeProjectionState) {
        model = MessageStreamModel(projection: projection)
    }

    public var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                ForEach(model.messages) { message in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(message.role == .user ? "You" : "Birkin")
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                        Text(message.text)
                            .textSelection(.enabled)
                        if message.state == .streaming {
                            ProgressView().controlSize(.small)
                                .accessibilityLabel("Assistant response streaming")
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
                }
            }
        }
        .accessibilityLabel("Conversation message stream")
    }
}

@MainActor
public final class ConversationComposerModel: ObservableObject {
    @Published public var draft: String
    @Published public var isCodeMode = false
    @Published public private(set) var visibleReason: String?

    public init(draft: String = "") {
        self.draft = draft
    }

    public var draftByteCount: Int {
        NativePayloadSizing.encodedByteCount(["text": .string(draft)])
    }

    @discardableResult
    public func send(
        availability: MutationAvailability,
        canSend: Bool,
        expectedCursor: Int,
        session: NativeReadySession,
        submit: (NativeCommandRequest) -> Void
    ) -> Bool {
        guard availability.isEnabled else {
            visibleReason = availability.disabledReason
            return false
        }
        guard session.supportedCommands.contains("chat.send"), canSend else {
            visibleReason = "Sending is not currently available."
            return false
        }
        guard !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            visibleReason = "Enter a message before sending."
            return false
        }
        let payload: NativeJSONObject = ["text": .string(draft)]
        let byteCount = NativePayloadSizing.encodedByteCount(payload)
        guard byteCount <= session.maxPayloadBytes else {
            visibleReason = "Payload is \(byteCount) bytes; the limit is \(session.maxPayloadBytes) bytes."
            return false
        }
        let id = UUID().uuidString.lowercased()
        submit(NativeCommandRequest(
            frameID: "command-\(id)",
            commandID: id,
            expectedCursor: expectedCursor,
            commandType: "chat.send",
            payload: payload,
            sessionCapability: session.sessionCapability,
            viewID: "main"
        ))
        draft = ""
        visibleReason = nil
        return true
    }
}

public enum SendKeyPolicy {
    public static func shouldSend(
        commandPressed: Bool,
        returnPressed: Bool,
        hasMarkedText: Bool
    ) -> Bool {
        commandPressed && returnPressed && !hasMarkedText
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
            Toggle("Code mode", isOn: $model.isCodeMode)
                .accessibilityLabel("Code mode")
            IMEAwareTextEditor(text: $model.draft, send: send)
                .frame(minHeight: 72)
                .font(model.isCodeMode ? .system(.body, design: .monospaced) : .body)
                .accessibilityLabel(model.isCodeMode ? "Code message draft" : "Message draft")
            HStack {
                Text("\(model.draftByteCount) bytes")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Send", action: send)
                    .keyboardShortcut(.return, modifiers: .command)
                    .accessibilityLabel("Send message")
                    .disabled(!isSendEnabled)
            }
            if let reason = model.visibleReason {
                Text(reason)
                    .font(.caption)
                    .foregroundStyle(.secondary)
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

        func textView(
            _ textView: NSTextView,
            doCommandBy commandSelector: Selector
        ) -> Bool {
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
