namespace Birkin.Native.Shell.Presentation;

public sealed record ErrorCodePresentation(
    string UserMessage,
    string DiagnosticDetail);

public static class KoreanDecisionText
{
    private const string UnknownErrorMessage =
        "요청을 처리할 수 없습니다. 잠시 후 다시 시도하고 계속되면 오류 코드를 확인하세요.";

    private static readonly IReadOnlyDictionary<string, string> ErrorMessages =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["E_CONNECTION_NOT_READY"] =
                "아직 연결되지 않았습니다. 연결이 완료된 뒤 다시 시도하세요.",
            ["E_CAPABILITY_EXPIRED"] =
                "세션 권한이 만료되었습니다. 다시 연결한 뒤 시도하세요.",
            ["E_COMMAND_UNADVERTISED"] =
                "현재 서버에서 이 작업을 지원하지 않습니다. 앱과 Birkin을 업데이트한 뒤 다시 시도하세요.",
            ["E_PROJECTION_FORBIDS_MUTATION"] =
                "현재 화면 상태에서는 변경할 수 없습니다. 최신 상태를 불러온 뒤 다시 시도하세요.",
            ["E_OFFICE_JOB_REQUEST_REQUIRED"] =
                "이 작업은 Office 승인 요청이 필요합니다. 승인 요청을 만든 뒤 계속하세요.",
            ["E_STALE_CURSOR"] =
                "작업 상태가 이미 변경되었습니다. 최신 내용을 확인한 뒤 다시 시도하세요.",
        };

    public static ErrorCodePresentation Error(
        string code,
        string? serverMessage = null,
        bool? retryable = null,
        long? currentCursor = null)
    {
        var userMessage = ErrorMessages.GetValueOrDefault(code, UnknownErrorMessage);
        var details = new List<string> { $"오류 코드: {code}" };
        if (!string.IsNullOrWhiteSpace(serverMessage))
        {
            details.Add($"서버 메시지: {serverMessage}");
        }
        if (retryable is not null)
        {
            details.Add($"다시 시도 가능: {(retryable.Value ? "예" : "아니요")}");
        }
        if (currentCursor is not null)
        {
            details.Add($"현재 커서: {currentCursor.Value}");
        }
        return new ErrorCodePresentation(userMessage, string.Join(Environment.NewLine, details));
    }

    public static string WorkflowState(WorkflowCommandState state) => state switch
    {
        WorkflowCommandState.Idle => string.Empty,
        WorkflowCommandState.PendingReceipt => "요청을 보내는 중입니다.",
        WorkflowCommandState.AcceptedPendingProjection => "결과를 확인하는 중입니다.",
        WorkflowCommandState.Refused => "요청이 거부되었습니다.",
        _ => "요청 상태를 확인하고 있습니다.",
    };

    public static string ConversationKind(string kind) => kind switch
    {
        "user" => "사용자",
        "assistant" => "Birkin",
        "system" => "시스템",
        "tool" => "도구",
        _ => "메시지",
    };

    public static string ApprovalCategory(string? category) => category switch
    {
        "office_job" => "Office 작업",
        "office_rollback" => "Office 되돌리기",
        "shell" => "Shell 명령",
        "filesystem" => "파일 변경",
        _ => "기타 작업",
    };

    public static string ApprovalRisk(string? risk) => risk switch
    {
        "low" => "낮은 위험",
        "medium" => "보통 위험",
        "high" => "높은 위험",
        "critical" => "매우 높은 위험",
        _ => "위험도 알 수 없음",
    };

    public static string ApprovalSeal(bool isSealed) =>
        isSealed ? "검토 내용 고정됨" : "검토 내용 고정 안 됨";

    public static string ApprovalOutcome(string? status) => status switch
    {
        "approved" => "승인됨",
        "rejected" => "거부됨",
        "answered_elsewhere" => "다른 위치에서 결정됨",
        "expired" => "만료됨",
        "failed" => "실패함",
        _ => "결정 대기 중",
    };

    public static string ApprovalOverwrite(bool? overwriteApproved) =>
        overwriteApproved switch
        {
            true => "주의: 기존 파일을 덮어쓸 수 있습니다",
            false => "안전: 기존 파일이 없어야 합니다",
            null => "덮어쓰기 권한을 확인할 수 없습니다",
        };
}
