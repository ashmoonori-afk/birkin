using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Shell.Presentation;

public sealed record OfficeDiffRowPresentation(string Label, string OldValue, string NewValue);

public enum OfficeDiffApprovalState
{
    BeforeApproval,
    Approved,
}

public sealed record OfficeDiffPresentation(
    string DiffId,
    IReadOnlyList<OfficeDiffRowPresentation> Rows,
    OfficeDiffApprovalState ApprovalState);

public static class OfficeDiffPresentationMapper
{
    public static OfficeDiffPresentation? FromCanonical(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.Event
            || Text(envelope.Body, "type") != "office.diff_ready"
            || Object(envelope.Body, "payload") is not { } payload
            || Object(payload, "result") is not { } result
            || Object(result, "diff") is not { } diff
            || Text(diff, "diff_id") is not { } diffId)
        {
            return null;
        }

        var rows = SemanticRows(diff);
        if (rows.Count == 0
            && Text(diff, "left") is { } oldValue
            && Text(diff, "right") is { } newValue
            && !string.Equals(oldValue, newValue, StringComparison.Ordinal))
        {
            rows = [new OfficeDiffRowPresentation("Value", oldValue, newValue)];
        }

        return rows.Count == 0
            ? null
            : new OfficeDiffPresentation(diffId, rows, OfficeDiffApprovalState.BeforeApproval);
    }

    public static bool IsCorrelatedApprovalReceipt(NativeEnvelope envelope, string diffId) =>
        envelope.Kind == NativeMessageKind.Event
        && Text(envelope.Body, "type") == "receipt.recorded"
        && Object(envelope.Body, "payload") is { } payload
        && string.Equals(Text(payload, "diff_id"), diffId, StringComparison.Ordinal)
        && Text(payload, "approval_id") is not null
        && Text(payload, "artifact_id") is not null;

    public static OfficeDiffRowPresentation FromProjected(PanelItemPresentation item)
    {
        var summary = item.Summary ?? string.Empty;
        var arrow = summary.IndexOf(" -> ", StringComparison.Ordinal);
        if (arrow < 0)
        {
            return new OfficeDiffRowPresentation("Projected difference", string.Empty, summary);
        }

        var labelEnd = summary.LastIndexOf(": ", arrow, StringComparison.Ordinal);
        var label = labelEnd < 0 ? "Change" : summary[..labelEnd];
        var oldStart = labelEnd < 0 ? 0 : labelEnd + 2;
        return new OfficeDiffRowPresentation(
            label,
            summary[oldStart..arrow],
            summary[(arrow + 4)..]);
    }

    private static IReadOnlyList<OfficeDiffRowPresentation> SemanticRows(NativeJsonObject diff)
    {
        if (Object(diff, "semantic") is not { } semantic
            || Object(semantic, "normalized_ir") is not { } normalized
            || normalized["left"] is not NativeJsonArray left
            || normalized["right"] is not NativeJsonArray right)
        {
            return [];
        }

        var oldNodes = left.Values.OfType<NativeJsonObject>().ToArray();
        var newNodes = right.Values.OfType<NativeJsonObject>().ToArray();
        var rows = new List<OfficeDiffRowPresentation>();
        for (var index = 0; index < Math.Max(oldNodes.Length, newNodes.Length); index++)
        {
            var oldNode = index < oldNodes.Length ? oldNodes[index] : null;
            var newNode = index < newNodes.Length ? newNodes[index] : null;
            if (oldNode is not null && newNode is not null
                && NativeJsonSerializer.Serialize(oldNode).AsSpan()
                    .SequenceEqual(NativeJsonSerializer.Serialize(newNode)))
            {
                continue;
            }

            var labelNode = oldNode ?? newNode;
            if (labelNode is null
                || Text(labelNode, "kind") is not { } kind
                || Integer(labelNode, "order") is not { } order)
            {
                continue;
            }

            rows.Add(new OfficeDiffRowPresentation(
                $"{kind} {order}",
                oldNode is null ? string.Empty : Text(oldNode, "text") ?? string.Empty,
                newNode is null ? string.Empty : Text(newNode, "text") ?? string.Empty));
        }
        return rows.AsReadOnly();
    }

    private static NativeJsonObject? Object(NativeJsonObject value, string key) =>
        value[key] as NativeJsonObject;

    private static string? Text(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text ? text.Value : null;

    private static long? Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer ? integer.Value : null;
}
