using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed class ShellCoordinator : IAsyncDisposable
{
    private readonly INativeClientConnection _connection;
    private readonly NativeProjectionStore _projectionStore;
    private readonly ShellPresentationModel _presentationModel;
    private readonly CancellationTokenSource _lifetimeCancellation = new();
    private Task _receiveTask = Task.CompletedTask;

    public ShellCoordinator(
        INativeClientConnection connection,
        NativeProjectionStore projectionStore,
        ShellPresentationModel presentationModel)
    {
        _connection = connection;
        _projectionStore = projectionStore;
        _presentationModel = presentationModel;
        _projectionStore.SnapshotApplied += OnProjectionSnapshotApplied;
    }

    public event Action<ConnectionState>? ConnectionStateChanged;

    public event Action<WorkspaceSnapshotPresentation>? SnapshotApplied;

    public async Task ConnectAsync(
        string announcementJson,
        string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        var receiveCancellation = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _lifetimeCancellation.Token);
        try
        {
            TransitionTo(ConnectionState.Connecting);
            var announcement = BridgeAnnouncement.Parse(announcementJson);
            TransitionTo(ConnectionState.Handshaking);
            await _connection.ConnectAsync(
                announcement,
                expectedProductVersion,
                receiveCancellation.Token).ConfigureAwait(false);
            TransitionTo(ConnectionState.Subscribing);
            var readyIdentity = new NativeReadyIdentity(
                announcement.SessionId,
                announcement.InstanceId,
                announcement.ServerVersion);
            NativeEnvelope snapshot;
            while (true)
            {
                snapshot = await _connection.ReceiveAsync(receiveCancellation.Token).ConfigureAwait(false);
                switch (snapshot.Kind.WireName)
                {
                    case "snapshot":
                        break;
                    case "ping":
                    case "capability.renewed":
                        continue;
                    default:
                        throw new NativeProtocolError("E_STATE", "subscription requires an initial snapshot");
                }
                break;
            }
            _projectionStore.ApplySnapshot(snapshot, readyIdentity);
            _receiveTask = Task.Run(
                () => ConsumeFramesAsync(readyIdentity, receiveCancellation),
                CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            receiveCancellation.Dispose();
            Fail("E_CANCELLED");
        }
        catch (NativeProtocolError error)
        {
            receiveCancellation.Dispose();
            Fail(error.Code);
        }
        catch (Exception)
        {
            receiveCancellation.Dispose();
            Fail("E_CONNECTION");
        }
    }

    public async ValueTask DisposeAsync()
    {
        _lifetimeCancellation.Cancel();
        await _receiveTask.ConfigureAwait(false);
        _projectionStore.SnapshotApplied -= OnProjectionSnapshotApplied;
        await _connection.DisposeAsync().ConfigureAwait(false);
        _lifetimeCancellation.Dispose();
    }

    private async Task ConsumeFramesAsync(
        NativeReadyIdentity readyIdentity,
        CancellationTokenSource receiveCancellation)
    {
        try
        {
            while (true)
            {
                var envelope = await _connection.ReceiveAsync(receiveCancellation.Token).ConfigureAwait(false);
                switch (envelope.Kind.WireName)
                {
                    case "snapshot":
                        _projectionStore.ApplySnapshot(envelope, readyIdentity);
                        break;
                    case "event":
                        _projectionStore.ApplyEvent(envelope);
                        if (_projectionStore.Status == NativeProjectionStoreStatus.Current)
                        {
                            var state = _projectionStore.State
                                ?? throw new NativeProtocolError("E_STATE", "current projection state is unavailable");
                            var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
                            _presentationModel.PresentSnapshot(snapshot, static () => { });
                        }
                        break;
                    case "surface_snapshot":
                    case "surface_event":
                        _projectionStore.ApplySurface(envelope);
                        break;
                    case "goodbye":
                        TransitionTo(ConnectionState.Disconnected);
                        return;
                    case "ping":
                    case "pong":
                    case "receipt":
                    case "error":
                    case "capability.renewed":
                    case "stream.desynchronized":
                        break;
                    default:
                        throw new NativeProtocolError("E_STATE", "server frame is not valid for the shell projection");
                }
            }
        }
        catch (OperationCanceledException) when (receiveCancellation.IsCancellationRequested)
        {
            if (!_lifetimeCancellation.IsCancellationRequested)
            {
                Fail("E_CANCELLED");
            }
        }
        catch (NativeProtocolError error)
        {
            Fail(error.Code);
        }
        catch (Exception)
        {
            Fail("E_CONNECTION");
        }
        finally
        {
            receiveCancellation.Dispose();
        }
    }

    private void OnProjectionSnapshotApplied(NativeProjectionState state)
    {
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        ConnectionStateChanged?.Invoke(ConnectionState.Ready);
        _presentationModel.PresentReadySnapshot(snapshot, () => SnapshotApplied?.Invoke(snapshot));
    }

    private void TransitionTo(ConnectionState state)
    {
        _presentationModel.PresentConnection(ConnectionPresentation.Create(state));
        ConnectionStateChanged?.Invoke(state);
    }

    private void Fail(string errorCode)
    {
        _presentationModel.PresentConnection(ConnectionPresentation.Failed(errorCode));
        ConnectionStateChanged?.Invoke(ConnectionState.Failed);
    }
}
