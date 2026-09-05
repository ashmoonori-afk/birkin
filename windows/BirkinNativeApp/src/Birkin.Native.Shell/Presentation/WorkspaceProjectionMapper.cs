using System.Collections.ObjectModel;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Shell.Presentation;

internal static class WorkspaceProjectionMapper
{
    private static readonly (string Label, string Category)[] ApprovalCategories =
    [
        ("파일 변경", "operation"),
        ("명령 실행", "shell"),
        ("네트워크 접근", "network"),
    ];

    public static WorkspaceSnapshotPresentation Map(NativeProjectionState state, string transport) =>
        new(
            state.ProtocolVersion,
            state.SessionId,
            state.Cursor,
            state.InstanceId,
            state.ResetReason,
            transport,
            state.Panels.Values.Count,
            Text(state.Status, "connection") ?? string.Empty,
            Conversation(state.Conversation),
            new ComposerPresentation(
                Flag(state.Composer, "can_send"),
                Flag(state.Composer, "can_interrupt"),
                Flag(state.Composer, "can_resume"),
                false),
            WorkingMemory(state.WorkingMemory),
            ApprovalRows(state.ApprovalPolicy),
            PanelItems(state.Panels, "approvals"),
            PanelItems(state.Panels, "activity_logs"),
            PanelItems(state.Panels, "browser_aside", "browser", "computer_use"),
            PanelItems(state.Panels, "office", "files_evidence"),
            new TerminalPresentation(false, state.Terminals.Values.Count),
            MutationAvailabilityPresentation.PhaseOne);

    private static IReadOnlyList<ConversationRowPresentation> Conversation(NativeJsonArray values) =>
        ReadOnly(values.Values.OfType<NativeJsonObject>().Select(item =>
            new ConversationRowPresentation(
                Text(item, "id") ?? string.Empty,
                Text(item, "kind") ?? string.Empty,
                Text(item, "text") ?? string.Empty,
                Text(item, "actor_id") ?? string.Empty,
                Integer(item, "cursor"))));

    private static WorkingMemoryPresentation WorkingMemory(NativeJsonObject memory)
    {
        var goal = Object(memory, "goal");
        var fields = Object(memory, "fields");
        return new WorkingMemoryPresentation(
            Integer(memory, "revision") ?? 0,
            ReadOnly(
            [
                MemoryRow("목표", goal is null ? [] : Values(goal, "objective"), "설정되지 않음"),
                MemoryRow("맥락", FieldValues(fields, "corrections", "decisions", "evidence"), "비어 있음"),
                MemoryRow("파일", ObjectSummaries(memory, "files_evidence"), "비어 있음"),
                MemoryRow("제약 조건", FieldValues(fields, "constraints"), "설정되지 않음"),
                MemoryRow("메모", FieldValues(fields, "incomplete", "next_actions"), "비어 있음"),
            ]));
    }

    private static WorkingMemoryRowPresentation MemoryRow(
        string label,
        IEnumerable<string> values,
        string emptyState) => new(label, ReadOnly(values), emptyState);

    private static IEnumerable<string> FieldValues(NativeJsonObject? fields, params string[] keys) =>
        fields is null
            ? []
            : keys.SelectMany(key => StringValues(fields[key]));

    private static IEnumerable<string> ObjectSummaries(NativeJsonObject value, string key) =>
        value[key] is NativeJsonArray array
            ? array.Values.OfType<NativeJsonObject>()
                .Select(item => Text(item, "summary"))
                .Where(summary => summary is not null)
                .Select(summary => summary!)
            : [];

    private static IReadOnlyList<ApprovalPolicyRowPresentation> ApprovalRows(NativeJsonObject policy)
    {
        var effective = AutoApprove(Object(policy, "effective")?["auto_approve"]);
        var requestedValue = Object(policy, "requested")?["auto_approve"];
        return ReadOnly(ApprovalCategories.Select(category => new ApprovalPolicyRowPresentation(
            category.Label,
            category.Category,
            effective.Contains(category.Category) ? "자동" : "확인",
            RequestedState(requestedValue, category.Category),
            false)));
    }

    private static HashSet<string> AutoApprove(NativeJsonValue? value) =>
        new(StringValues(value), StringComparer.Ordinal);

    private static string RequestedState(NativeJsonValue? value, string category) => value switch
    {
        null or NativeJsonNull => "기본값",
        NativeJsonString text => string.Equals(text.Value, category, StringComparison.Ordinal)
            ? "자동"
            : "확인",
        NativeJsonArray => AutoApprove(value).Contains(category) ? "자동" : "확인",
        _ => "잘못된 값",
    };

    private static IReadOnlyList<PanelItemPresentation> PanelItems(
        NativeJsonArray panels,
        params string[] keys)
    {
        var panel = panels.Values.OfType<NativeJsonObject>().FirstOrDefault(item =>
            keys.Contains(Text(item, "key"), StringComparer.Ordinal));
        if (panel?["items"] is not NativeJsonArray items)
        {
            return Array.Empty<PanelItemPresentation>();
        }

        return ReadOnly(items.Values.OfType<NativeJsonObject>().Select(item =>
            new PanelItemPresentation(
                Text(item, "id"),
                Text(item, "kind"),
                Text(item, "summary") ?? Text(item, "text"),
                Text(item, "description"),
                Text(item, "category"),
                Text(item, "risk"),
                Flag(item, "sealed"),
                IsDecided(item),
                Text(item, "source_filename"),
                Text(item, "destination"),
                OptionalFlag(item, "overwrite_approved"),
                Text(item, "authority_digest"),
                Text(item, "requester"),
                Text(item, "rejection_result"),
                Text(item, "expires_at"),
                Text(item, "receipt_ref"),
                Flag(item, "backup_exists"),
                Text(item, "status"))));
    }

    private static IEnumerable<string> Values(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? [text.Value] : [];

    private static IEnumerable<string> StringValues(NativeJsonValue? value) =>
        value is NativeJsonArray array
            ? array.Values.OfType<NativeJsonString>().Select(item => item.Value)
            : [];

    private static NativeJsonObject? Object(NativeJsonObject value, string key) =>
        value[key] as NativeJsonObject;

    private static string? Text(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? text.Value : null;

    private static long? Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer ? integer.Value : null;

    private static bool Flag(NativeJsonObject value, string key) =>
        value[key] is NativeJsonBoolean { Value: true };

    private static bool IsDecided(NativeJsonObject value) =>
        Flag(value, "decided")
        || Text(value, "status") is
            "approved" or "rejected" or "answered_elsewhere" or "expired" or "failed";

    private static bool? OptionalFlag(NativeJsonObject value, string key) =>
        value[key] is NativeJsonBoolean flag ? flag.Value : null;

    private static ReadOnlyCollection<T> ReadOnly<T>(IEnumerable<T> values) =>
        Array.AsReadOnly(values.ToArray());
}
