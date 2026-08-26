using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Projection;

internal static partial class NativeProjectionReducer
{
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

}
