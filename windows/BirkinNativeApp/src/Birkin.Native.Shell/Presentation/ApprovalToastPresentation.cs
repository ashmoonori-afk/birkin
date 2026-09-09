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
            "승인 요청이 도착했습니다",
            "Birkin에서 요청 내용을 확인하세요.",
            "approvals",
            []);
    }
}
