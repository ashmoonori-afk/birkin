import BirkinNativeProtocol
import Foundation

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
    public let rows: [ConversationRow]

    public init(projection: NativeProjectionState) {
        rows = ConversationRows.parse(projection: projection)
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

@MainActor
public final class ConversationComposerModel: ObservableObject {
    @Published public var draft: String
    @Published public var isCodeMode = false
    @Published public private(set) var attachments: [ImportedReference] = []
    @Published public private(set) var visibleReason: String?

    public init(draft: String = "") {
        self.draft = draft
    }

    public var draftByteCount: Int {
        NativePayloadSizing.encodedByteCount(payload)
    }

    public func attach(_ reference: ImportedReference) {
        guard !attachments.contains(where: { $0.importID == reference.importID }) else { return }
        attachments.append(reference)
        visibleReason = nil
    }

    public func removeAttachment(importID: String) {
        attachments.removeAll { $0.importID == importID }
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
        let commandPayload = payload
        let byteCount = NativePayloadSizing.encodedByteCount(commandPayload)
        guard byteCount <= session.maxPayloadBytes else {
            visibleReason = "Payload is \(byteCount) bytes; the limit is \(session.maxPayloadBytes) bytes."
            return false
        }
        let id = UUID().uuidString.lowercased()
        submit(NativeCommandRequest(
            frameID: "command-\(id)", commandID: id,
            expectedCursor: expectedCursor, commandType: "chat.send",
            payload: commandPayload, sessionCapability: session.sessionCapability,
            viewID: "main"
        ))
        draft = ""
        attachments = []
        visibleReason = nil
        return true
    }

    private var payload: NativeJSONObject {
        var value: NativeJSONObject = ["text": .string(draft)]
        if !attachments.isEmpty {
            try? value.append(
                key: "attachments",
                value: .array(attachments.map { .object($0.canonicalJSONObject) })
            )
        }
        return value
    }
}

public enum ShellTextInputField: String, CaseIterable, Equatable, Sendable {
    case composer
    case codeEditor = "code-editor"
    case sessionRename = "session-rename"
    case workingMemoryEditor = "working-memory-editor"
    case officeName = "office-name"
    case terminal

    fileprivate var acceptsSendCommand: Bool {
        self == .composer || self == .codeEditor
    }
}

public struct SendKeyResult: Equatable, Sendable {
    public let shouldSend: Bool
    public let text: String
}

public enum SendKeyPolicy {
    public static func shouldSend(
        commandPressed: Bool, returnPressed: Bool, hasMarkedText: Bool
    ) -> Bool {
        commandPressed && returnPressed && !hasMarkedText
    }

    public static func evaluate(
        field: ShellTextInputField,
        commandPressed: Bool,
        returnPressed: Bool,
        hasMarkedText: Bool,
        text: String
    ) -> SendKeyResult {
        SendKeyResult(
            shouldSend: field.acceptsSendCommand && shouldSend(
                commandPressed: commandPressed,
                returnPressed: returnPressed,
                hasMarkedText: hasMarkedText
            ),
            text: text
        )
    }
}
