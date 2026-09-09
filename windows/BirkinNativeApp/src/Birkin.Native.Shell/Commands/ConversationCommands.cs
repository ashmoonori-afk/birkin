using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell.Commands;

public sealed record CommandRequestContext(string CommandId, long ExpectedCursor, string ViewId);

public static class ConversationCommands
{
    public const string CommandType = "chat.send";
    public const string InterruptCommandType = "chat.interrupt";

    public static NativeCommandRequest Send(
        string draft,
        CommandRequestContext context,
        IEnumerable<ImportedFilePresentation>? attachments = null)
    {
        if (string.IsNullOrWhiteSpace(draft))
        {
            throw new ArgumentException("Conversation draft must contain text.", nameof(draft));
        }

        var payload = new List<KeyValuePair<string, NativeJsonValue>>([
            new("text", new NativeJsonString(draft)),
        ]);
        if (attachments?.Select(Reference).ToArray() is { Length: > 0 } references)
        {
            payload.Add(new("attachments", new NativeJsonArray(references)));
        }

        return new NativeCommandRequest(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                CommandType,
                new NativeJsonObject(payload)),
            context.ViewId);
    }

    private static NativeJsonObject Reference(ImportedFilePresentation attachment) => new([
        new("kind", new NativeJsonString("workspace_import")),
        new("import_id", new NativeJsonString(attachment.ImportId)),
        new("display_name", new NativeJsonString(attachment.DisplayName)),
        new("jail_name", new NativeJsonString(attachment.JailName)),
        new("sha256", new NativeJsonString(attachment.Sha256)),
        new("byte_count", new NativeJsonInteger(attachment.ByteCount)),
    ]);

    public static NativeCommandRequest Interrupt(CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                InterruptCommandType,
                new NativeJsonObject([])),
            context.ViewId);
}
