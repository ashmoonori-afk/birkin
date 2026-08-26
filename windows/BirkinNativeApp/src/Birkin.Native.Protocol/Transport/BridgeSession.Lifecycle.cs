using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class BridgeSession
{
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
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
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

    public async ValueTask DisposeAsync()
    {
        // Request cancellation before taking the gate so a reconnect blocked in connection setup
        // can leave the gate. Actual teardown and the disposed transition remain serialized below.
        if (Interlocked.Exchange(ref _shutdownRequested, 1) == 0)
        {
            _shutdown.Cancel();
        }

        await _lifecycleGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
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
            _lifetime = null;
            _receiveTask = null;
            _shutdown.Dispose();
        }
        finally
        {
            _lifecycleGate.Release();
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

}
