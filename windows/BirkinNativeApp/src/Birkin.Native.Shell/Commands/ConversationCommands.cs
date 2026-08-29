using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public sealed record CommandRequestContext(string CommandId, long ExpectedCursor, string ViewId);

public static class ConversationCommands
{
    public const string CommandType = "chat.send";
    public const string InterruptCommandType = "chat.interrupt";

    public static NativeCommandRequest Send(string draft, CommandRequestContext context)
    {
        if (string.IsNullOrWhiteSpace(draft))
        {
            throw new ArgumentException("Conversation draft must contain text.", nameof(draft));
        }

        return new NativeCommandRequest(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                CommandType,
                new NativeJsonObject([
                    new("text", new NativeJsonString(draft)),
                ])),
            context.ViewId);
    }

    public static NativeCommandRequest Interrupt(CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                InterruptCommandType,
                new NativeJsonObject([])),
            context.ViewId);
}
