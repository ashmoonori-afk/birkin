import BirkinNativeProtocol

public enum ConversationRowKind: Equatable, Sendable {
    case user
    case assistant
    case tool
    case approval
    case question
    case receipt
    case failure
    case interrupted
}

public enum ConversationRowState: Equatable, Sendable {
    case complete
    case streaming
    case running
    case actionNeeded
    case succeeded
    case blocked
    case failed
    case interrupted
    case pending
}

public struct CanonicalFailurePresentation: Equatable, Sendable {
    public let code: String?
    public let message: String
    public let retryable: Bool
}

public struct ConversationRow: Equatable, Identifiable, Sendable {
    public let id: String
    public let kind: ConversationRowKind
    public let state: ConversationRowState
    public let cursor: Int?
    public let title: String
    public let text: String
    public let attachments: [ImportedReference]
    public let failure: CanonicalFailurePresentation?
}

public enum ConversationRows {
    public static func parse(
        conversation: [NativeJSONObject],
        approvals: [NativeJSONObject] = [],
        activity: [NativeJSONObject] = []
    ) -> [ConversationRow] {
        let rows = conversation.compactMap(message) + approvals.compactMap(panelItem)
            + activity.compactMap(panelItem)
        return rows.enumerated().sorted { lhs, rhs in
            let left = lhs.element.cursor ?? Int.max
            let right = rhs.element.cursor ?? Int.max
            return left == right ? lhs.offset < rhs.offset : left < right
        }.map(\.element)
    }

    public static func parse(projection: NativeProjectionState) -> [ConversationRow] {
        parse(
            conversation: projection.conversation,
            approvals: projection.panels.first { $0.key == "approvals" }?.items ?? [],
            activity: projection.panels.first { $0.key == "activity_logs" }?.items ?? []
        )
    }

    private static func message(_ raw: NativeJSONObject) -> ConversationRow? {
        guard let id = raw.string("id"), let kind = raw.string("kind"),
              let text = raw.string("text") else { return nil }
        let attachments = raw.objectArray("attachments").compactMap {
            ImportedReference(.object($0))
        }
        switch kind {
        case "user_message":
            return ConversationRow(
                id: id, kind: .user, state: .complete, cursor: raw.int("cursor"), title: "You",
                text: text, attachments: attachments, failure: nil
            )
        case "assistant_stream", "assistant_message":
            return ConversationRow(
                id: id, kind: .assistant,
                state: kind == "assistant_stream" ? .streaming : .complete,
                cursor: raw.int("cursor"), title: "Birkin", text: text,
                attachments: [], failure: nil
            )
        default: return nil
        }
    }

    private static func panelItem(_ raw: NativeJSONObject) -> ConversationRow? {
        guard let id = raw.string("id"), let rawKind = raw.string("kind") else { return nil }
        let summary = raw.string("summary") ?? raw.string("message") ?? rawKind
        let uiState = raw.string("ui_state") ?? raw.string("state") ?? "pending"
        let kind: ConversationRowKind
        switch rawKind {
        case "approval": kind = .approval
        case "question": kind = .question
        case "receipt": kind = .receipt
        case "failure": kind = .failure
        case "interrupted": kind = .interrupted
        default:
            if uiState == "failed" { kind = .failure }
            else if uiState == "paused" || raw.string("status") == "interrupted" {
                kind = .interrupted
            } else { kind = .tool }
        }
        let failure = kind == .failure ? CanonicalFailurePresentation(
            code: raw.string("code") ?? raw.string("refusal_code"),
            message: String((raw.string("message") ?? summary).prefix(300)),
            retryable: raw.bool("retryable") ?? false
        ) : nil
        return ConversationRow(
            id: id, kind: kind, state: state(uiState, kind: kind),
            cursor: raw.int("cursor"), title: title(kind), text: summary,
            attachments: [], failure: failure
        )
    }

    private static func state(_ raw: String, kind: ConversationRowKind) -> ConversationRowState {
        if kind == .interrupted { return .interrupted }
        switch raw {
        case "streaming": return .streaming
        case "running": return .running
        case "action_needed": return .actionNeeded
        case "succeeded", "completed": return .succeeded
        case "blocked": return .blocked
        case "failed": return .failed
        default: return .pending
        }
    }

    private static func title(_ kind: ConversationRowKind) -> String {
        switch kind {
        case .user: "You"
        case .assistant: "Birkin"
        case .tool: "Tool"
        case .approval: "Approval required"
        case .question: "Question"
        case .receipt: "Receipt"
        case .failure: "Failed"
        case .interrupted: "Interrupted"
        }
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func bool(_ key: String) -> Bool? {
        guard case .bool(let value) = self[key] else { return nil }
        return value
    }

    func int(_ key: String) -> Int? {
        guard case .int(let value) = self[key] else { return nil }
        return value
    }

    func objectArray(_ key: String) -> [NativeJSONObject] {
        guard case .array(let values) = self[key] else { return [] }
        return values.compactMap { value in
            guard case .object(let object) = value else { return nil }
            return object
        }
    }
}
