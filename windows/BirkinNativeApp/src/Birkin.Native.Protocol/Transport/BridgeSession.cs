using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

/// <summary>Owns the sole receive loop for one subscribed bridge connection.</summary>
public sealed class BridgeSession : INativeClientConnection
{
    private readonly NativeClientConnection _connection;
    private readonly CancellationTokenSource _shutdown = new();
    private readonly object _pendingGate = new();
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private CancellationTokenSource? _lifetime;
    private Task? _receiveTask;
    private TaskCompletionSource _initialSnapshot = NewSignal();
    private PendingCommand? _pendingCommand;
    private int _activeReceives;
    private int _maximumConcurrentReceives;
    private bool _disposed;
    private NativeReadyIdentity? _readyIdentity;

    public BridgeSession(NativeProjectionStore projectionStore)
        : this(new NativeClientConnection(projectionStore), projectionStore)
    {
    }

    internal BridgeSession(NativeClientConnection connection, NativeProjectionStore projectionStore)
    {
        ArgumentNullException.ThrowIfNull(connection);
        ArgumentNullException.ThrowIfNull(projectionStore);
        if (!ReferenceEquals(connection.ProjectionStore, projectionStore))
        {
            throw new ArgumentException("session and connection must share one projection store", nameof(projectionStore));
        }

        _connection = connection;
        _connection.UseExternalCanonicalRepairOwner();
        ProjectionStore = projectionStore;
        _connection.AuthorityUnavailable += OnAuthorityUnavailable;
        _connection.SnapshotInFlight += OnSnapshotInFlight;
    }

    public bool OwnsReceiveLoop => true;

    public NativeProjectionStore ProjectionStore { get; }

    public int MaximumConcurrentReceives => Volatile.Read(ref _maximumConcurrentReceives);

    public int CanonicalRepairRequestCount { get; private set; }

    public IReadOnlySet<string> AdvertisedCommands => _connection.AdvertisedCommands;

    public bool HasLiveCapability(DateTimeOffset now) =>
        !_disposed && _connection.HasLiveCapability(now);

    public async Task ConnectAsync(
        BridgeAnnouncement announcement,
        string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_receiveTask is not null)
        {
            throw new NativeProtocolError("E_STATE", "session is already active");
        }

        _readyIdentity = new NativeReadyIdentity(
            announcement.SessionId,
            announcement.InstanceId,
            expectedProductVersion);
        ProjectionStore.BeginSnapshot(_readyIdentity);
        _lifetime = CancellationTokenSource.CreateLinkedTokenSource(_shutdown.Token, cancellationToken);
        await _connection.ConnectAsync(announcement, expectedProductVersion, _lifetime.Token).ConfigureAwait(false);
        _receiveTask = ReceiveLoopAsync(_lifetime.Token);
        await _initialSnapshot.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task ReconnectAsync(
        BridgeAnnouncement announcement,
        string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var lifetime = _lifetime;
            lifetime?.Cancel();
            if (_receiveTask is not null)
            {
                try
                {
                    await _receiveTask.ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                }
            }

            await _connection.DisposeAsync().ConfigureAwait(false);
            lifetime?.Dispose();
            _lifetime = null;
            _receiveTask = null;
            _initialSnapshot = NewSignal();
            await ConnectAsync(announcement, expectedProductVersion, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    public ValueTask SendCommandAsync(
        NativeCommandRequest request,
        CancellationToken cancellationToken) =>
        throw new NativeProtocolError(
            "E_STATE",
            "session commands must await their correlated result");

    public async ValueTask<NativeEnvelope> SendCommandForResultAsync(
        NativeCommandRequest request,
        CancellationToken cancellationToken)
    {
        EnsureMutable();
        var completion = new TaskCompletionSource<NativeEnvelope>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (_pendingGate)
        {
            if (_pendingCommand is not null)
            {
                throw new NativeProtocolError("E_FLOW_VIOLATION", "session already has a pending command");
            }

            _pendingCommand = new PendingCommand(request.CommandId, completion);
        }

        try
        {
            await _connection.SendCommandAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            ClearPending(completion);
            throw;
        }

        using var registration = cancellationToken.Register(
            static state => ((CancellationTokenSource?)state)?.Cancel(),
            _lifetime);
        return await completion.Task.ConfigureAwait(false);
    }

    public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken) =>
        ValueTask.FromException<NativeEnvelope>(new NativeProtocolError(
            "E_STATE",
            "session receive is owned by its lifetime pump"));

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _shutdown.Cancel();
        if (_receiveTask is not null)
        {
            try
            {
                await _receiveTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        FaultPending(new OperationCanceledException("bridge session stopped"));
        ProjectionStore.MarkMutationAuthorityUnavailable();
        _connection.AuthorityUnavailable -= OnAuthorityUnavailable;
        _connection.SnapshotInFlight -= OnSnapshotInFlight;
        await _connection.DisposeAsync().ConfigureAwait(false);
        _lifetime?.Dispose();
        _lifecycleGate.Dispose();
        _shutdown.Dispose();
    }

    private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
    {
        Exception? terminalError = null;
        try
        {
            while (true)
            {
                NativeEnvelope envelope;
                try
                {
                    var active = Interlocked.Increment(ref _activeReceives);
                    UpdateMaximumConcurrentReceives(active);
                    try
                    {
                        envelope = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
                    }
                    finally
                    {
                        _ = Interlocked.Decrement(ref _activeReceives);
                    }
                }
                catch (NativeCommandRefusal refusal)
                {
                    CompletePending(refusal.CommandId, refusal);
                    continue;
                }

                await RouteAsync(envelope, cancellationToken).ConfigureAwait(false);
                if (envelope.Kind == NativeMessageKind.Goodbye)
                {
                    return;
                }
            }
        }
        catch (OperationCanceledException error) when (cancellationToken.IsCancellationRequested)
        {
            terminalError = error;
        }
        catch (Exception error)
        {
            terminalError = error;
            _initialSnapshot.TrySetException(error);
        }
        finally
        {
            ProjectionStore.MarkMutationAuthorityUnavailable();
            FaultPending(terminalError ?? new IOException("bridge session disconnected"));
        }
    }

    private async ValueTask RouteAsync(NativeEnvelope envelope, CancellationToken cancellationToken)
    {
        switch (envelope.Kind.WireName)
        {
            case "snapshot":
                ProjectionStore.ApplySnapshot(
                    envelope,
                    _readyIdentity ?? throw new NativeProtocolError("E_STATE", "session identity is unavailable"));
                ProjectionStore.MarkMutationAuthorityAvailable();
                _initialSnapshot.TrySetResult();
                break;
            case "event":
                ProjectionStore.ApplyEvent(envelope);
                break;
            case "surface_snapshot":
            case "surface_event":
                ProjectionStore.ApplySurface(envelope);
                break;
            case "receipt":
                CompletePending(String(envelope.Body, "command_id"), envelope);
                break;
            case "error":
            case "goodbye":
                ProjectionStore.MarkMutationAuthorityUnavailable();
                break;
            case "stream.desynchronized":
                ProjectionStore.ApplyStreamSignal(envelope);
                break;
            case "ping":
            case "pong":
            case "capability.renewed":
                break;
            default:
                throw new NativeProtocolError("E_STATE", "session received an invalid subscribed frame");
        }

        if (ProjectionStore.TryBeginReplay())
        {
            FaultPending(new IOException("canonical projection repair is required"));
            CanonicalRepairRequestCount++;
            var afterCursor = envelope.Kind == NativeMessageKind.StreamDesynchronized
                && envelope.Body["resume_after"] is NativeJsonInteger resumeAfter
                    ? resumeAfter.Value
                    : ProjectionStore.State?.Cursor ?? 0;
            await _connection.RequestCanonicalReplayAsync(afterCursor, cancellationToken).ConfigureAwait(false);
        }
    }

    public void ReportHeartbeatMiss()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        _ = ProjectionStore.RequestCanonicalRepair(NativeProjectionRepairReason.HeartbeatMiss);
        FaultPending(new IOException("bridge heartbeat was missed"));
    }

    public async ValueTask ReportHeartbeatMissAsync(CancellationToken cancellationToken)
    {
        ReportHeartbeatMiss();
        if (ProjectionStore.TryBeginReplay())
        {
            CanonicalRepairRequestCount++;
            await _connection.RequestCanonicalReplayAsync(
                ProjectionStore.State?.Cursor ?? 0,
                cancellationToken).ConfigureAwait(false);
        }
    }

    private void CompletePending(string commandId, object result)
    {
        TaskCompletionSource<NativeEnvelope>? completion = null;
        lock (_pendingGate)
        {
            if (_pendingCommand is not { } pending
                || !string.Equals(pending.CommandId, commandId, StringComparison.Ordinal))
            {
                throw new NativeProtocolError("E_CORRELATION", "command result has no matching session waiter");
            }

            completion = pending.Completion;
            _pendingCommand = null;
        }

        if (result is NativeEnvelope envelope)
        {
            completion.TrySetResult(envelope);
        }
        else
        {
            completion.TrySetException((Exception)result);
        }
    }

    private void FaultPending(Exception error)
    {
        TaskCompletionSource<NativeEnvelope>? completion;
        lock (_pendingGate)
        {
            completion = _pendingCommand?.Completion;
            _pendingCommand = null;
        }
        completion?.TrySetException(error);
    }

    private void ClearPending(TaskCompletionSource<NativeEnvelope> expected)
    {
        lock (_pendingGate)
        {
            if (ReferenceEquals(_pendingCommand?.Completion, expected))
            {
                _pendingCommand = null;
            }
        }
    }

    private void OnSnapshotInFlight(NativeReadyIdentity identity)
    {
        _readyIdentity = identity;
        ProjectionStore.BeginSnapshot(identity);
    }

    private void OnAuthorityUnavailable()
    {
        ProjectionStore.MarkMutationAuthorityUnavailable();
        FaultPending(_shutdown.IsCancellationRequested
            ? new OperationCanceledException("bridge session stopped")
            : new IOException("bridge connection unavailable"));
    }

    private void EnsureMutable()
    {
        if (_disposed
            || _receiveTask is null
            || !ProjectionStore.IsMutationAuthorityAvailable
            || !_connection.HasLiveCapability(DateTimeOffset.UtcNow))
        {
            throw new NativeProtocolError("E_STATE", "session mutation authority is unavailable");
        }
    }

    private void UpdateMaximumConcurrentReceives(int active)
    {
        var observed = Volatile.Read(ref _maximumConcurrentReceives);
        while (active > observed)
        {
            var previous = Interlocked.CompareExchange(ref _maximumConcurrentReceives, active, observed);
            if (previous == observed)
            {
                return;
            }
            observed = previous;
        }
    }

    private static string String(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString text
            ? text.Value
            : throw new NativeProtocolError("E_BODY", "command result string is invalid");

    private static TaskCompletionSource NewSignal() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private sealed record PendingCommand(
        string CommandId,
        TaskCompletionSource<NativeEnvelope> Completion);
}
