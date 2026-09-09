using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public static class SessionCommands
{
    public const string CreateCommandType = "session.create";
    public const string SelectCommandType = "session.select";
    public const string RenameCommandType = "session.rename";

    public static NativeCommandRequest Create(string sessionId, CommandRequestContext context) =>
        Request(CreateCommandType, sessionId, null, context);

    public static NativeCommandRequest Select(string sessionId, CommandRequestContext context) =>
        Request(SelectCommandType, sessionId, null, context);

    public static NativeCommandRequest Rename(string sessionId, string name, CommandRequestContext context) =>
        Request(RenameCommandType, sessionId, name, context);

    private static NativeCommandRequest Request(
        string commandType,
        string sessionId,
        string? name,
        CommandRequestContext context)
    {
        var payload = new List<KeyValuePair<string, NativeJsonValue>>
        {
            new("session_id", new NativeJsonString(sessionId)),
        };
        if (name is not null)
        {
            payload.Add(new("name", new NativeJsonString(name)));
        }
        return new NativeCommandRequest(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(commandType, new NativeJsonObject(payload)),
            context.ViewId);
    }
}
