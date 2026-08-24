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
        try
        {
            TransitionTo(ConnectionState.Connecting);
            var announcement = BridgeAnnouncement.Parse(announcementJson);
            TransitionTo(ConnectionState.Handshaking);
            await _connection.ConnectAsync(announcement, expectedProductVersion, cancellationToken).ConfigureAwait(false);
            TransitionTo(ConnectionState.Subscribing);
            var snapshot = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
            var readyIdentity = new NativeReadyIdentity(
                announcement.SessionId,
                announcement.InstanceId,
                announcement.ServerVersion);
            _projectionStore.ApplySnapshot(snapshot, readyIdentity);
        }
        catch (OperationCanceledException)
        {
            Fail("E_CANCELLED");
        }
        catch (NativeProtocolError error)
        {
            Fail(error.Code);
        }
        catch (Exception)
        {
            Fail("E_CONNECTION");
        }
    }

    public async ValueTask DisposeAsync()
    {
        _projectionStore.SnapshotApplied -= OnProjectionSnapshotApplied;
        await _connection.DisposeAsync().ConfigureAwait(false);
    }

    private void OnProjectionSnapshotApplied(NativeProjectionState state)
    {
        var snapshot = new WorkspaceSnapshotPresentation(
            state.ProtocolVersion,
            state.SessionId,
            state.Cursor,
            state.InstanceId,
            state.ResetReason,
            "loopback",
            state.Panels.Values.Count);
        TransitionTo(ConnectionState.Ready);
        _presentationModel.PresentSnapshot(snapshot, () => SnapshotApplied?.Invoke(snapshot));
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
