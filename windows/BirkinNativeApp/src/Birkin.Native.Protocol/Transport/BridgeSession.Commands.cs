using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class BridgeSession
{
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
