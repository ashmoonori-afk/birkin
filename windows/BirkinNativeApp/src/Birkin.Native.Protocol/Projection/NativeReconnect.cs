using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Projection;

public static class NativeReconnect
{
    public static NativeProjectionSubscription Prepare(
        NativeProjectionStore store,
        NativeReadyIdentity readyIdentity)
    {
        var state = store.State;
        if (state is not null
            && !string.Equals(state.InstanceId, readyIdentity.InstanceId, StringComparison.Ordinal))
        {
            store.DiscardForInstanceChange();
            return Canonical(store.SurfaceRevisions);
        }
        if (state is null
            || store.Status == NativeProjectionStoreStatus.RepairRequired
            || store.RecoveryState != NativeProjectionRecoveryState.Live)
        {
            return Canonical(store.SurfaceRevisions);
        }
        return new NativeProjectionSubscription(
            state.Cursor,
            state.InstanceId,
            store.SurfaceRevisions,
            isCanonicalRepair: false);
    }

    private static NativeProjectionSubscription Canonical(
        IReadOnlyDictionary<string, long> surfaceRevisions) =>
        new(
            0,
            null,
            surfaceRevisions.ToDictionary(pair => pair.Key, _ => 0L, StringComparer.Ordinal),
            isCanonicalRepair: true);
}
