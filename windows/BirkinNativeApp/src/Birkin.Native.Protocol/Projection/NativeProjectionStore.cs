using System.Collections.ObjectModel;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Projection;

public enum NativeProjectionStoreStatus
{
    Empty,
    Current,
    RepairRequired,
}

public enum NativeProjectionRepairReason
{
    CursorGap,
    StreamDesynchronized,
    CursorAhead,
    SurfaceGap,
    HeartbeatMiss,
}

public enum NativeProjectionRecoveryState
{
    Disconnected,
    SnapshotInFlight,
    Live,
    GapDetected,
    ReplayInFlight,
}

public sealed record NativeSurfaceProjection(string Name, long Revision, NativeJsonObject Payload);

/// <summary>Owns the latest validated Python projection in memory.</summary>
public sealed class NativeProjectionStore
{
    private readonly HashSet<string> _activeCommands = new(StringComparer.Ordinal);
    private readonly Dictionary<string, NativeSurfaceProjection> _surfaces = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> _surfaceRevisions = new(StringComparer.Ordinal);

    public NativeProjectionState? State { get; private set; }

    public NativeProjectionStoreStatus Status { get; private set; }

    public NativeProjectionRepairReason? RepairReason { get; private set; }

    public bool IsMutationAuthorityAvailable { get; private set; }

    public NativeProjectionRecoveryState RecoveryState { get; private set; }

    public IReadOnlyDictionary<string, long> SurfaceRevisions =>
        new ReadOnlyDictionary<string, long>(_surfaceRevisions);

    public event Action<NativeProjectionState>? SnapshotApplied;

    public event Action<NativeEnvelope>? CanonicalApplied;

    public event Action<bool>? MutationAuthorityChanged;

    public event Action<NativeProjectionRecoveryState>? RecoveryStateChanged;

    public void ApplySnapshot(NativeEnvelope envelope, NativeReadyIdentity readyIdentity)
    {
        if (envelope.Kind != NativeMessageKind.Snapshot)
        {
            throw new NativeProtocolError("E_STATE", "projection application requires a snapshot envelope");
        }

        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
        var replacement = new NativeProjectionState(envelope.Body, readyIdentity);
        State = replacement;
        Status = NativeProjectionStoreStatus.Current;
        RepairReason = null;
        TransitionRecoveryTo(NativeProjectionRecoveryState.Live);
        _activeCommands.Clear();
        if (replacement.Composer["can_interrupt"] is NativeJsonBoolean { Value: true })
        {
            _ = _activeCommands.Add("__snapshot_active__");
        }
        SetMutationAuthorityAvailable(true);
        SnapshotApplied?.Invoke(replacement);
    }

    public void ApplyEvent(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.Event)
        {
            throw new NativeProtocolError("E_STATE", "projection application requires an event envelope");
        }
        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
        if (RecoveryState != NativeProjectionRecoveryState.Live)
        {
            return;
        }

        var current = State ?? throw new NativeProtocolError("E_STATE", "event requires a projection snapshot");
        var protocolVersion = Integer(envelope.Body, "protocol_version");
        var sessionId = String(envelope.Body, "session_id");
        if (protocolVersion != current.ProtocolVersion
            || !string.Equals(sessionId, current.SessionId, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_IDENTITY", "event identity differs from projection identity");
        }

        var cursor = Integer(envelope.Body, "cursor");
        if (cursor <= current.Cursor)
        {
            throw new NativeProtocolError("E_CURSOR", "event cursor is not increasing");
        }
        if (cursor != current.Cursor + 1)
        {
            RequestCanonicalRepair(NativeProjectionRepairReason.CursorGap);
            return;
        }

        State = NativeProjectionReducer.Reduce(current, envelope.Body, _activeCommands);
        Status = NativeProjectionStoreStatus.Current;
        RepairReason = null;
        CanonicalApplied?.Invoke(envelope);
    }

    public void ApplySurface(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.SurfaceSnapshot
            && envelope.Kind != NativeMessageKind.SurfaceEvent)
        {
            throw new NativeProtocolError("E_STATE", "surface application requires a surface envelope");
        }
        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
        if (RecoveryState != NativeProjectionRecoveryState.Live)
        {
            return;
        }

        var name = String(envelope.Body, "surface");
        var revision = Integer(envelope.Body, "revision");
        var payload = envelope.Body["payload"] as NativeJsonObject ?? throw BodyError();
        if (envelope.Kind == NativeMessageKind.SurfaceEvent
            && (!_surfaces.TryGetValue(name, out var current) || revision != current.Revision + 1))
        {
            _ = _surfaces.Remove(name);
            _surfaceRevisions[name] = 0;
            RequestCanonicalRepair(NativeProjectionRepairReason.SurfaceGap);
            return;
        }

        _surfaces[name] = new NativeSurfaceProjection(name, revision, payload);
        _surfaceRevisions[name] = revision;
        CanonicalApplied?.Invoke(envelope);
    }

    public NativeSurfaceProjection? Surface(string name) => _surfaces.GetValueOrDefault(name);

    public void ApplyStreamSignal(NativeEnvelope envelope)
    {
        if (envelope.Kind != NativeMessageKind.StreamDesynchronized)
        {
            throw new NativeProtocolError("E_STATE", "stream signal is not desynchronized");
        }
        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
        RequestCanonicalRepair(NativeProjectionRepairReason.StreamDesynchronized);
    }

    public bool RequestCanonicalRepair(NativeProjectionRepairReason reason)
    {
        Status = NativeProjectionStoreStatus.RepairRequired;
        RepairReason ??= reason;
        SetMutationAuthorityAvailable(false);
        if (RecoveryState is NativeProjectionRecoveryState.GapDetected
            or NativeProjectionRecoveryState.ReplayInFlight)
        {
            return false;
        }

        TransitionRecoveryTo(NativeProjectionRecoveryState.GapDetected);
        return true;
    }

    internal bool TryBeginReplay()
    {
        if (RecoveryState != NativeProjectionRecoveryState.GapDetected)
        {
            return false;
        }

        TransitionRecoveryTo(NativeProjectionRecoveryState.ReplayInFlight);
        return true;
    }

    internal void BeginSnapshot(NativeReadyIdentity identity)
    {
        if (State is { } current
            && !string.Equals(current.InstanceId, identity.InstanceId, StringComparison.Ordinal))
        {
            DiscardForInstanceChange();
        }

        SetMutationAuthorityAvailable(false);
        TransitionRecoveryTo(NativeProjectionRecoveryState.SnapshotInFlight);
    }

    public void MarkMutationAuthorityUnavailable()
    {
        SetMutationAuthorityAvailable(false);
        TransitionRecoveryTo(NativeProjectionRecoveryState.Disconnected);
    }

    internal void MarkMutationAuthorityAvailable()
    {
        if (RecoveryState == NativeProjectionRecoveryState.Live)
        {
            SetMutationAuthorityAvailable(true);
        }
    }

    internal void DiscardForInstanceChange()
    {
        State = null;
        Status = NativeProjectionStoreStatus.Empty;
        RepairReason = null;
        _activeCommands.Clear();
        _surfaces.Clear();
        _surfaceRevisions.Clear();
        SetMutationAuthorityAvailable(false);
    }

    private void TransitionRecoveryTo(NativeProjectionRecoveryState state)
    {
        if (RecoveryState == state)
        {
            return;
        }

        RecoveryState = state;
        RecoveryStateChanged?.Invoke(state);
    }

    private void SetMutationAuthorityAvailable(bool available)
    {
        if (IsMutationAuthorityAvailable == available)
        {
            return;
        }

        IsMutationAuthorityAvailable = available;
        MutationAuthorityChanged?.Invoke(available);
    }

    private static long Integer(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger { Value: >= 0 } value ? value.Value : throw BodyError();

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString value ? value.Value : throw BodyError();

    private static NativeProtocolError BodyError() =>
        new("E_BODY", "projection body is invalid");
}
