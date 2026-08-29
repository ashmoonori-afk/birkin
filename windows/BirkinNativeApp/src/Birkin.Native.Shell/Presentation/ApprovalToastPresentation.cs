namespace Birkin.Native.Shell.Presentation;

public sealed record ApprovalToastContent(
    string ApprovalId,
    string Title,
    string Body,
    string Route,
    IReadOnlyList<string> DecisionActions)
{
    public static ApprovalToastContent For(string approvalId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(approvalId);
        return new(
            approvalId,
            "Approval requested",
            "Open Birkin to review this request.",
            "approvals",
            []);
    }
}
