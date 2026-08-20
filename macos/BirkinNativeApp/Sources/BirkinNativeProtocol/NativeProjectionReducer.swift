struct NativeProjectionEvent {
    let protocolVersion: Int
    let sessionID: String
    let cursor: Int
    let eventID: String
    let type: String
    let actorID: String
    let commandID: String
    let payload: NativeJSONObject
}

enum NativeProjectionReducer {
    private static let panelByEvent = [
        "task.updated": "tasks_runs", "run.updated": "tasks_runs",
        "approval.requested": "approvals", "approval.answered": "approvals",
        "question.requested": "approvals", "question.answered": "approvals",
        "evidence.added": "files_evidence", "file.updated": "files_evidence",
        "session.updated": "sessions_history", "activity.recorded": "activity_logs",
        "receipt.recorded": "activity_logs", "integrity.warning": "activity_logs",
        "command.completed": "activity_logs",
        "cron.updated": "cron", "memory.updated": "memory_skills",
        "skill.updated": "memory_skills", "checkpoint.created": "checkpoints_restore",
        "checkpoint.restored": "checkpoints_restore", "computer.updated": "computer_use",
        "progress.updated": "activity_logs", "tool.started": "activity_logs",
        "tool.completed": "activity_logs", "tool.failed": "activity_logs",
        "settings.updated": "settings_status", "status.updated": "settings_status",
    ]

    static func reduce(
        _ state: inout NativeProjectionState,
        event: NativeProjectionEvent,
        activeCommands: inout Set<String>,
        interrupted: inout Bool
    ) {
        switch event.type {
        case "command.started": activeCommands.insert(event.commandID)
        case "command.completed", "command.failed":
            if activeCommands.remove(event.commandID) == nil {
                activeCommands.remove("__snapshot_active__")
            }
        case "turn.interrupted": interrupted = true
        case "turn.resumed": interrupted = false
        default: break
        }

        if event.type == "message.user", let text = event.payload.string("text") {
            state.conversation.append(message(event: event, kind: "user_message", text: text))
        } else if event.type == "message.assistant.delta",
                  let text = event.payload.string("text") {
            appendAssistantDelta(text, event: event, state: &state)
        } else if event.type == "message.assistant.completed",
                  let text = event.payload.string("text") {
            let value = message(event: event, kind: "assistant_message", text: text)
            if state.conversation.last?.string("kind") == "assistant_stream" {
                state.conversation[state.conversation.count - 1] = value
            } else {
                state.conversation.append(value)
            }
            append(value, toPanel: "sessions_history", state: &state)
        }
        if let panelKey = panelByEvent[event.type] {
            append(panelItem(event), toPanel: panelKey, state: &state)
        }
        if event.type == "working_memory.updated" {
            applyWorkingMemory(event.payload, state: &state)
        }
        applyTerminal(event, state: &state)

        state.cursor = event.cursor
        state.composer.canSend = activeCommands.isEmpty
        state.composer.canInterrupt = !activeCommands.isEmpty
        state.composer.canResume = interrupted && activeCommands.isEmpty
    }

    private static func applyTerminal(
        _ event: NativeProjectionEvent,
        state: inout NativeProjectionState
    ) {
        guard let terminalID = event.payload.string("terminal_id") else { return }
        if event.type == "terminal.opened" {
            let lease = event.payload.string("lease")
            let terminal = NativeTerminalProjection(
                terminalID: terminalID,
                cwd: event.payload.string("cwd") ?? "",
                screen: "",
                outputSequence: 0,
                state: "running",
                exitStatus: nil,
                columns: 80,
                rows: 24,
                lease: lease,
                readOnly: lease == nil
            )
            if let index = state.terminals.firstIndex(where: { $0.terminalID == terminalID }) {
                state.terminals[index] = terminal
            } else {
                state.terminals.append(terminal)
            }
            return
        }
        guard let index = state.terminals.firstIndex(
            where: { $0.terminalID == terminalID }
        ) else { return }
        switch event.type {
        case "terminal.output":
            guard case .int(let sequence) = event.payload["sequence"],
                  sequence == state.terminals[index].outputSequence + 1,
                  let data = event.payload.string("data") else { return }
            state.terminals[index].screen = boundedScreen(
                state.terminals[index].screen + data
            )
            state.terminals[index].outputSequence = sequence
        case "terminal.resized":
            if case .int(let columns) = event.payload["columns"] {
                state.terminals[index].columns = columns
            }
            if case .int(let rows) = event.payload["rows"] {
                state.terminals[index].rows = rows
            }
        case "terminal.exited":
            state.terminals[index].state = "exited"
            state.terminals[index].lease = nil
            state.terminals[index].readOnly = true
            if case .int(let status) = event.payload["exit_status"] {
                state.terminals[index].exitStatus = status
            }
        case "terminal.failed":
            state.terminals[index].state = "failed"
            state.terminals[index].lease = nil
            state.terminals[index].readOnly = true
        default: break
        }
    }

    private static func boundedScreen(_ value: String) -> String {
        guard value.utf8.count > 65_536 else { return value }
        var bounded = value
        while bounded.utf8.count > 65_536 {
            bounded.removeFirst()
        }
        return bounded
    }

    private static func applyWorkingMemory(
        _ payload: NativeJSONObject,
        state: inout NativeProjectionState
    ) {
        guard case .object(let effective) = payload["working_memory"],
              case .int(let revision) = effective["revision"] else { return }
        var fields = state.workingMemory.fields
        for key in fields.keys {
            guard case .array(let values) = effective[key] else { continue }
            let strings = values.compactMap { value -> String? in
                guard case .string(let text) = value else { return nil }
                return text
            }
            fields[key] = strings
        }
        state.workingMemory.revision = revision
        state.workingMemory.fields = fields
    }

    private static func appendAssistantDelta(
        _ text: String,
        event: NativeProjectionEvent,
        state: inout NativeProjectionState
    ) {
        if let last = state.conversation.last,
           last.string("kind") == "assistant_stream",
           let current = last.string("text") {
            state.conversation[state.conversation.count - 1] = [
                "id": last["id"]!,
                "kind": .string("assistant_stream"),
                "text": .string(current + text),
                "actor_id": last["actor_id"]!,
                "cursor": .int(event.cursor),
            ]
        } else {
            state.conversation.append(
                message(event: event, kind: "assistant_stream", text: text)
            )
        }
    }

    private static func message(
        event: NativeProjectionEvent,
        kind: String,
        text: String
    ) -> NativeJSONObject {
        [
            "id": .string(event.eventID), "kind": .string(kind), "text": .string(text),
            "actor_id": .string(event.actorID), "cursor": .int(event.cursor),
        ]
    }

    private static func append(
        _ item: NativeJSONObject,
        toPanel key: String,
        state: inout NativeProjectionState
    ) {
        guard let index = state.panels.firstIndex(where: { $0.key == key }) else { return }
        state.panels[index].items.append(item)
    }

    private static func panelItem(_ event: NativeProjectionEvent) -> NativeJSONObject {
        let payload = event.payload
        let decision = payload.string("decision")
        let id = payload.string("approval_id") ?? payload.string("question_id")
            ?? payload.string("task_id") ?? payload.string("evidence_id")
            ?? payload.string("checkpoint_id") ?? event.eventID
        let summary = payload.string("summary") ?? payload.string("name") ?? event.type
        let status = payload.string("status") ?? decision ?? event.type.split(separator: ".").last.map(String.init)!
        let kind = [
            "task.updated": "task", "approval.requested": "approval",
            "approval.answered": "approval", "question.requested": "question",
            "question.answered": "question", "evidence.added": "evidence",
            "checkpoint.created": "checkpoint", "checkpoint.restored": "checkpoint",
            "computer.updated": "computer_use", "receipt.recorded": "receipt",
            "command.completed": "receipt", "integrity.warning": "integrity_warning",
        ][event.type] ?? "activity"
        let defaultState = defaultUIState(event.type, decision: decision, payload: payload)
        var item: NativeJSONObject = [
            "id": .string(id), "summary": .string(summary), "status": .string(status),
            "cursor": .int(event.cursor), "kind": .string(kind),
            "ui_state": .string(payload.string("ui_state") ?? defaultState),
        ]
        for field in [
            "requester", "description", "category", "target", "expected_impact", "rejection_result",
            "related_evidence", "risk", "expires_at", "receipt_ref", "snapshot_ref",
            "effect", "refusal_code",
        ] {
            if let value = payload.string(field), !value.isEmpty {
                try? item.append(key: field, value: .string(value))
            }
        }
        for field in ["sealed", "decided"] {
            if case .bool(let value) = payload[field] {
                try? item.append(key: field, value: .bool(value))
            }
        }
        if case .int(let sequence) = payload["computer_sequence"] {
            try? item.append(key: "computer_sequence", value: .int(sequence))
        }
        if case .bool(let preserved) = payload["focus_preserved"] {
            try? item.append(key: "focus_preserved", value: .bool(preserved))
        }
        return item
    }

    private static func defaultUIState(
        _ type: String,
        decision: String?,
        payload: NativeJSONObject
    ) -> String {
        switch type {
        case "approval.requested", "question.requested": return "action_needed"
        case "approval.answered": return decision == "approve" ? "succeeded" : "blocked"
        case "question.answered", "evidence.added", "checkpoint.restored": return "succeeded"
        case "task.updated", "tool.started": return "running"
        case "tool.completed": return "succeeded"
        case "tool.failed": return "failed"
        case "computer.updated": return payload.string("ui_state") ?? "pending"
        default: return "pending"
        }
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
