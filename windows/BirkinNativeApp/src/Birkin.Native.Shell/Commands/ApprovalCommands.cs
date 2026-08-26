using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Commands;

public enum ApprovalDecision
{
    Approve,
    Reject,
}

public sealed record ApprovalAnswerIntent(string ApprovalId, ApprovalDecision Decision);

public static class ApprovalCommands
{
    public const string CommandType = "approval.answer";

    public static NativeCommandRequest Answer(ApprovalAnswerIntent intent, CommandRequestContext context) =>
        new(
            new NativeCommandIdentity(context.CommandId, context.ExpectedCursor),
            new NativeCommandIntent(
                CommandType,
                new NativeJsonObject([
                    new("approval_id", new NativeJsonString(intent.ApprovalId)),
                    new("decision", new NativeJsonString(intent.Decision switch
                    {
                        ApprovalDecision.Approve => "approve",
                        ApprovalDecision.Reject => "reject",
                        _ => throw new ArgumentOutOfRangeException(nameof(intent)),
                    })),
                ])),
            context.ViewId);
}
