namespace Birkin.Native.Shell.Presentation;

public sealed record ApprovalAttentionSignal(string ApprovalId);

public sealed class ApprovalAttentionTracker
{
    private readonly HashSet<string> _seen = new(StringComparer.Ordinal);

    public int PendingCount { get; private set; }

    public ApprovalAttentionSignal? Observe(
        IReadOnlyList<PanelItemPresentation> approvals)
    {
        var pending = approvals
            .Where(item =>
                string.Equals(item.Kind, "approval", StringComparison.Ordinal)
                && !item.Decided
                && !string.IsNullOrWhiteSpace(item.Id))
            .Select(item => item.Id!)
            .ToArray();
        var pendingIds = pending.ToHashSet(StringComparer.Ordinal);
        _seen.IntersectWith(pendingIds);
        var added = pending.FirstOrDefault(id => !_seen.Contains(id));
        _seen.UnionWith(pendingIds);
        PendingCount = pendingIds.Count;
        return added is null ? null : new ApprovalAttentionSignal(added);
    }
}
