using System.Text;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Projection;

internal static partial class NativeProjectionReducer
{
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
        if (PanelByEvent.TryGetValue(type, out var panel))
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
