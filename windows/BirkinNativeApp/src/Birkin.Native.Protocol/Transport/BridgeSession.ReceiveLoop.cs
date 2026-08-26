using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class BridgeSession
{
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
                    if (string.Equals(refusal.Code, "E_STALE_CURSOR", StringComparison.Ordinal)
                        && refusal.CurrentCursor is { } currentCursor
                        && currentCursor > (ProjectionStore.State?.Cursor ?? 0))
                    {
                        _ = ProjectionStore.RequestCanonicalRepair(NativeProjectionRepairReason.CursorAhead);
                        if (ProjectionStore.TryBeginReplay())
                        {
                            CanonicalRepairRequestCount++;
                            await _connection.RequestCanonicalSnapshotAsync(cancellationToken).ConfigureAwait(false);
                        }
                    }
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

}
