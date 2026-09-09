using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public static class WorkItemCommands
{
    public const string RequestCommandType = "work_item.request";
    public const string OpenSourceCommandType = "work_item.open_source";

    public static NativeCommandRequest Complete(string id, CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(RequestCommandType, new NativeJsonObject([
                new("action", new NativeJsonString("complete")),
                new("id", new NativeJsonString(id)),
            ])),
            context.ViewId);

    public static NativeCommandRequest Update(string id, string? assignee, DateTime? dueDate, CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(RequestCommandType, new NativeJsonObject([
                new("action", new NativeJsonString("update")),
                new("id", new NativeJsonString(id)),
                new("assignee", assignee is null ? NativeJsonNull.Value : new NativeJsonString(assignee)),
                new("due_date", dueDate is null ? NativeJsonNull.Value : new NativeJsonString(dueDate.Value.ToString("yyyy-MM-dd"))),
            ])),
            context.ViewId);

    public static NativeCommandRequest OpenSource(string id, CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(OpenSourceCommandType, new NativeJsonObject([
                new("id", new NativeJsonString(id)),
            ])),
            context.ViewId);
}
