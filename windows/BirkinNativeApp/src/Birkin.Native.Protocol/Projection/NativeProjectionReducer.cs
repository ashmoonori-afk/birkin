using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Projection;

internal static class NativeProjectionReducer
{
    private const int MaxActivityItems = 100;
    private static readonly IReadOnlyDictionary<string, string> PanelByEvent = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["task.updated"] = "tasks_runs",
        ["approval.requested"] = "approvals",
        ["receipt.recorded"] = "activity_logs",
        ["integrity.warning"] = "activity_logs",
        ["command.completed"] = "activity_logs",
        ["progress.updated"] = "activity_logs",
        ["tool.started"] = "activity_logs",
        ["tool.completed"] = "activity_logs",
        ["tool.failed"] = "activity_logs",
        ["notification.requested"] = "activity_logs",
    };

    public static NativeProjectionState Reduce(
        NativeProjectionState state, NativeJsonObject body, HashSet<string> activeCommands)
    {
        var type = String(body, "type");
        var commandId = String(body, "command_id");
        var cursor = Integer(body, "cursor");
        var payload = Object(body, "payload");
        if (type == "command.started")
        {
            _ = activeCommands.Add(commandId);
        }
        else if (type is "command.completed" or "command.failed")
        {
            if (!activeCommands.Remove(commandId))
            {
                _ = activeCommands.Remove("__snapshot_active__");
            }
        }

        var conversation = state.Conversation.Values.ToList();
        var panels = state.Panels.Values.Cast<NativeJsonObject>().ToList();
        var terminals = state.Terminals.Values.Cast<NativeJsonObject>().ToList();
        ApplyConversation(conversation, panels, body, type, payload, cursor);
        if (type == "approval.answered")
        {
            ReconcileApproval(panels, body, payload, cursor);
        }
        else if (PanelByEvent.TryGetValue(type, out var panel))
        {
            AppendPanel(panels, panel, PanelItem(body, type, payload, cursor));
        }
        ApplyTerminal(terminals, type, payload);

        var composer = new NativeJsonObject([
            new("can_send", new NativeJsonBoolean(activeCommands.Count == 0)),
            new("can_interrupt", new NativeJsonBoolean(activeCommands.Count != 0)),
            new("can_resume", new NativeJsonBoolean(false)),
        ]);
        return state.WithBody(Replace(state.ToBody(),
            ("cursor", new NativeJsonInteger(cursor)),
            ("panels", new NativeJsonArray(panels)),
            ("conversation", new NativeJsonArray(conversation)),
            ("composer", composer),
            ("terminals", new NativeJsonArray(terminals))));
    }

    private static void ApplyConversation(
        List<NativeJsonValue> conversation,
        List<NativeJsonObject> panels,
        NativeJsonObject body,
        string type,
        NativeJsonObject payload,
        long cursor)
    {
        var text = OptionalString(payload, "text");
        if (text is null)
        {
            return;
        }
        if (type == "message.user")
        {
            conversation.Add(Message(body, "user_message", text, cursor));
        }
        else if (type == "message.assistant.delta")
        {
            if (conversation.LastOrDefault() is NativeJsonObject last
                && OptionalString(last, "kind") == "assistant_stream")
            {
                conversation[^1] = new NativeJsonObject([
                    new("id", last["id"]!),
                    new("kind", new NativeJsonString("assistant_stream")),
                    new("text", new NativeJsonString(String(last, "text") + text)),
                    new("actor_id", last["actor_id"]!),
                    new("cursor", new NativeJsonInteger(cursor)),
                ]);
            }
            else
            {
                conversation.Add(Message(body, "assistant_stream", text, cursor));
            }
        }
        else if (type == "message.assistant.completed")
        {
            var message = Message(body, "assistant_message", text, cursor);
            if (conversation.LastOrDefault() is NativeJsonObject last
                && OptionalString(last, "kind") == "assistant_stream")
            {
                conversation[^1] = message;
            }
            else
            {
                conversation.Add(message);
            }
            AppendPanel(panels, "sessions_history", message);
        }
    }

    private static NativeJsonObject Message(
        NativeJsonObject body,
        string kind,
        string text,
        long cursor) => new([
            new("id", body["event_id"]!),
            new("kind", new NativeJsonString(kind)),
            new("text", new NativeJsonString(text)),
            new("actor_id", body["actor_id"]!),
            new("cursor", new NativeJsonInteger(cursor)),
        ]);

    private static NativeJsonObject PanelItem(
        NativeJsonObject body,
        string type,
        NativeJsonObject payload,
        long cursor)
    {
        var id = OptionalString(payload, "approval_id")
            ?? OptionalString(payload, "task_id")
            ?? OptionalString(payload, "notification_id")
            ?? String(body, "event_id");
        var status = OptionalString(payload, "outcome")
            ?? OptionalString(payload, "status")
            ?? (type == "approval.answered"
                ? null
                : OptionalString(payload, "decision"))
            ?? type[(type.LastIndexOf(".", StringComparison.Ordinal) + 1)..];
        var kind = type switch
        {
            "task.updated" => "task",
            "approval.requested" or "approval.answered" => "approval",
            "receipt.recorded" or "command.completed" => "receipt",
            "integrity.warning" => "integrity_warning",
            "notification.requested" => "notification",
            _ => "activity",
        };
        var projectedUiState = OptionalString(payload, "ui_state");
        var uiState = IsUiState(projectedUiState)
            ? projectedUiState!
            : type switch
            {
                "task.updated" => "running",
                "approval.requested" => "action_needed",
                "approval.answered" => ApprovalAnsweredState(payload),
                "tool.started" => "running",
                "tool.completed" => "succeeded",
                "tool.failed" => "failed",
                "notification.requested" => "action_needed",
                _ => "pending",
            };
        var pairs = new List<KeyValuePair<string, NativeJsonValue>>
        {
            new("id", new NativeJsonString(id)),
            new("summary", new NativeJsonString(OptionalString(payload, "summary") ?? type)),
            new("status", new NativeJsonString(status)),
            new("cursor", new NativeJsonInteger(cursor)),
            new("kind", new NativeJsonString(kind)),
            new("ui_state", new NativeJsonString(uiState)),
        };
        foreach (var field in new[]
        {
            "requester", "description", "category", "target", "expected_impact",
            "rejection_result", "related_evidence", "risk", "issued_at", "expires_at",
            "receipt_ref", "snapshot_ref", "effect", "refusal_code", "session_id",
            "name", "destination", "source_filename", "authority_digest",
            "office_phase", "job_id", "validation_summary",
            "visual_validation_summary",
        })
        {
            if (OptionalString(payload, field) is { Length: > 0 } value)
            {
                pairs.Add(new(field, new NativeJsonString(value)));
            }
        }
        if (type == "receipt.recorded")
        {
            foreach (var field in new[]
            {
                "approval_id", "artifact_id", "draft_id", "diff_id",
                "request_command_id", "approval_command_id",
            })
            {
                if (OptionalString(payload, field) is { Length: > 0 } value)
                {
                    pairs.Add(new(field, new NativeJsonString(value)));
                }
            }
        }
        foreach (var field in new[]
        {
            "sealed", "decided", "overwrite_approved", "backup_exists",
        })
        {
            if (payload[field] is NativeJsonBoolean value)
            {
                pairs.Add(new(field, value));
            }
        }
        if (type == "approval.answered")
        {
            if (!pairs.Any(pair => pair.Key == "decided"))
            {
                pairs.Add(new(
                    "decided",
                    new NativeJsonBoolean(ApprovalAnswerIsResolved(payload))));
            }
            if (!pairs.Any(pair => pair.Key == "receipt_ref")
                && OptionalString(payload, "receipt") is { Length: > 0 } receipt)
            {
                pairs.Add(new("receipt_ref", new NativeJsonString(receipt)));
            }
        }
        return new NativeJsonObject(pairs);
    }

    private static string ApprovalAnsweredState(NativeJsonObject payload) =>
        OptionalString(payload, "outcome") switch
        {
            "approved" => "succeeded",
            "rejected" => "blocked",
            _ => "failed",
        };

    private static bool ApprovalAnswerIsResolved(NativeJsonObject payload) =>
        OptionalString(payload, "outcome") is
            "approved" or "rejected" or "answered_elsewhere";

    private static void ReconcileApproval(
        List<NativeJsonObject> panels,
        NativeJsonObject body,
        NativeJsonObject payload,
        long cursor)
    {
        var approvalId = OptionalString(payload, "approval_id");
        var panelIndex = panels.FindIndex(
            panel => OptionalString(panel, "key") == "approvals");
        if (approvalId is null
            || panelIndex < 0
            || panels[panelIndex]["items"] is not NativeJsonArray items)
        {
            return;
        }
        var resolved = PanelItem(body, "approval.answered", payload, cursor);
        var values = items.Values.ToList();
        var itemIndex = values.FindIndex(
            item => item is NativeJsonObject approval
                && OptionalString(approval, "id") == approvalId);
        if (itemIndex < 0)
        {
            values.Add(resolved);
        }
        else
        {
            values[itemIndex] = Merge(
                (NativeJsonObject)values[itemIndex],
                resolved,
                [
                    "status",
                    "cursor",
                    "kind",
                    "ui_state",
                    "decided",
                    "receipt_ref",
                    "destination",
                    "issued_at",
                    "expires_at",
                    "backup_exists",
                    "validation_summary",
                    "visual_validation_summary",
                    "effect",
                    "refusal_code",
                ]);
        }
        panels[panelIndex] = Replace(
            panels[panelIndex],
            ("items", new NativeJsonArray(values)));
    }

    private static NativeJsonObject Merge(
        NativeJsonObject original,
        NativeJsonObject updates,
        HashSet<string> replacementKeys)
    {
        var result = new List<KeyValuePair<string, NativeJsonValue>>();
        foreach (var pair in original.Pairs)
        {
            var value = replacementKeys.Contains(pair.Key)
                ? updates[pair.Key] ?? pair.Value
                : pair.Value;
            result.Add(new(pair.Key, value));
        }
        foreach (var pair in updates.Pairs)
        {
            if (replacementKeys.Contains(pair.Key)
                && result.All(existing => existing.Key != pair.Key))
            {
                result.Add(pair);
            }
        }
        return new NativeJsonObject(result);
    }

    private static void AppendPanel(
        List<NativeJsonObject> panels,
        string key,
        NativeJsonObject item)
    {
        var index = panels.FindIndex(panel => OptionalString(panel, "key") == key);
        if (index < 0 || panels[index]["items"] is not NativeJsonArray items)
        {
            return;
        }
        var values = items.Values.Append(item);
        if (string.Equals(key, "activity_logs", StringComparison.Ordinal))
        {
            values = values.TakeLast(MaxActivityItems);
        }
        panels[index] = Replace(
            panels[index],
            ("items", new NativeJsonArray(values)));
    }

    private static bool IsUiState(string? value) => value is
        "action_needed"
        or "blocked"
        or "failed"
        or "paused"
        or "pending"
        or "running"
        or "succeeded";

    private static void ApplyTerminal(
        List<NativeJsonObject> terminals, string type, NativeJsonObject payload)
    {
        var terminalId = OptionalString(payload, "terminal_id");
        if (terminalId is null)
        {
            return;
        }
        var index = terminals.FindIndex(item => OptionalString(item, "terminal_id") == terminalId);
        if (type == "terminal.opened")
        {
            var terminal = new NativeJsonObject([
                new("terminal_id", new NativeJsonString(terminalId)),
                new("cwd", new NativeJsonString(OptionalString(payload, "cwd") ?? string.Empty)),
                new("screen", new NativeJsonString(string.Empty)),
                new("output_sequence", new NativeJsonInteger(0)),
                new("state", new NativeJsonString("running")),
                new("exit_status", NativeJsonNull.Value),
                new("columns", new NativeJsonInteger(80)),
                new("rows", new NativeJsonInteger(24)),
                new("lease", NativeJsonNull.Value),
                new("read_only", new NativeJsonBoolean(true)),
            ]);
            if (index < 0)
            {
                terminals.Add(terminal);
            }
            else
            {
                terminals[index] = terminal;
            }
            return;
        }
        if (index < 0)
        {
            return;
        }
        var current = terminals[index];
        terminals[index] = type switch
        {
            "terminal.output" => Replace(current,
                ("screen", new NativeJsonString(String(current, "screen") + (OptionalString(payload, "data") ?? string.Empty))),
                ("output_sequence", payload["sequence"] ?? current["output_sequence"]!)),
            "terminal.resized" => Replace(current,
                ("columns", payload["columns"] ?? current["columns"]!),
                ("rows", payload["rows"] ?? current["rows"]!)),
            "terminal.exited" => Replace(current,
                ("state", new NativeJsonString("exited")),
                ("exit_status", payload["exit_status"] ?? NativeJsonNull.Value),
                ("lease", NativeJsonNull.Value),
                ("read_only", new NativeJsonBoolean(true))),
            _ => current,
        };
    }

    private static NativeJsonObject Replace(
        NativeJsonObject source,
        params (string Key, NativeJsonValue Value)[] replacements)
    {
        var values = replacements.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
        return new NativeJsonObject(source.Pairs.Select(pair =>
            new KeyValuePair<string, NativeJsonValue>(pair.Key, values.GetValueOrDefault(pair.Key, pair.Value))));
    }

    private static NativeJsonObject Object(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject ?? throw BodyError();

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger integer ? integer.Value : throw BodyError();

    private static string String(NativeJsonObject body, string key) =>
        OptionalString(body, key) ?? throw BodyError();

    private static string? OptionalString(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text ? text.Value : null;

    private static NativeProtocolError BodyError() => new("E_BODY", "projection event body is invalid");
}
