using System.Collections.ObjectModel;

namespace Birkin.Native.Protocol.Projection;

/// <summary>Replay hints for the next authenticated subscription.</summary>
public sealed class NativeProjectionSubscription
{
    internal NativeProjectionSubscription(
        long afterCursor,
        string? knownInstanceId,
        IReadOnlyDictionary<string, long> surfaceRevisions,
        bool isCanonicalRepair)
    {
        AfterCursor = afterCursor;
        KnownInstanceId = knownInstanceId;
        SurfaceRevisions = new ReadOnlyDictionary<string, long>(
            new Dictionary<string, long>(surfaceRevisions, StringComparer.Ordinal));
        IsCanonicalRepair = isCanonicalRepair;
    }

    public long AfterCursor { get; }

    public string? KnownInstanceId { get; }

    public IReadOnlyDictionary<string, long> SurfaceRevisions { get; }

    public bool IsCanonicalRepair { get; }
}
