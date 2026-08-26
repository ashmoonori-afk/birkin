using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Projection;

internal static partial class NativeProjectionReducer
{
    private static readonly IReadOnlyDictionary<string, string> PanelByEvent = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["task.updated"] = "tasks_runs",
        ["approval.requested"] = "approvals",
        ["receipt.recorded"] = "activity_logs",
        ["integrity.warning"] = "activity_logs",
        ["command.completed"] = "activity_logs",
    };

    private static NativeJsonObject PanelItem(
        NativeJsonObject body,
        string type,
        NativeJsonObject payload,
        long cursor)
    {
        var id = OptionalString(payload, "approval_id")
            ?? OptionalString(payload, "task_id")
            ?? String(body, "event_id");
        var status = OptionalString(payload, "outcome")
            ?? OptionalString(payload, "status")
            ?? type[(type.LastIndexOf(".", StringComparison.Ordinal) + 1)..];
        var kind = type switch
        {
            "task.updated" => "task",
            "approval.requested" => "approval",
            "receipt.recorded" or "command.completed" => "receipt",
            "integrity.warning" => "integrity_warning",
            _ => "activity",
        };
        var uiState = type switch
        {
            "task.updated" => "running",
            "approval.requested" => "action_needed",
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
        foreach (var field in new[] { "description", "category", "risk", "receipt_ref" })
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
        foreach (var field in new[] { "sealed", "decided" })
        {
            if (payload[field] is NativeJsonBoolean value)
            {
                pairs.Add(new(field, value));
            }
        }
        return new NativeJsonObject(pairs);
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
        panels[index] = Replace(panels[index], ("items", new NativeJsonArray(items.Values.Append(item))));
    }

}
