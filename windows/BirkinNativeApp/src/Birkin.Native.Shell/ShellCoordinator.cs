using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator : IAsyncDisposable
{
    private readonly INativeClientConnection _connection;
    private readonly NativeProjectionStore _projectionStore;
    private readonly ShellPresentationModel _presentationModel;
    private ConnectionState _connectionState = ConnectionState.Disconnected;

    public ShellCoordinator(
        INativeClientConnection connection,
        NativeProjectionStore projectionStore,
        ShellPresentationModel presentationModel)
    {
        _connection = connection;
        _projectionStore = projectionStore;
        _presentationModel = presentationModel;
        if (_connection.OwnsReceiveLoop
            && !ReferenceEquals(_connection.ProjectionStore, _projectionStore))
        {
            throw new ArgumentException("session and coordinator must share one projection store", nameof(projectionStore));
        }
        _projectionStore.SnapshotApplied += OnProjectionSnapshotApplied;
        _projectionStore.CanonicalApplied += OnCanonicalApplied;
        _projectionStore.MutationAuthorityChanged += OnMutationAuthorityChanged;
    }

    public NativeProjectionStore ProjectionStore => _projectionStore;

    public Func<string> CommandIdFactory { get; init; } =
        () => $"windows-{Guid.NewGuid():N}";

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
            TransitionTo(ConnectionState.Subscribing);
            await _connection.ConnectAsync(announcement, expectedProductVersion, cancellationToken).ConfigureAwait(false);
            if (!_connection.OwnsReceiveLoop)
            {
                var snapshot = await _connection.ReceiveAsync(cancellationToken).ConfigureAwait(false);
                var readyIdentity = new NativeReadyIdentity(
                    announcement.SessionId,
                    announcement.InstanceId,
                    announcement.ServerVersion);
                _projectionStore.ApplySnapshot(snapshot, readyIdentity);
            }
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
        _projectionStore.CanonicalApplied -= OnCanonicalApplied;
        _projectionStore.MutationAuthorityChanged -= OnMutationAuthorityChanged;
        ClearWorkflowAuthority();
        await _connection.DisposeAsync().ConfigureAwait(false);
    }

    private void OnProjectionSnapshotApplied(NativeProjectionState state)
    {
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        _connectionState = ConnectionState.Ready;
        RefreshMutationAvailability();
        ConnectionStateChanged?.Invoke(ConnectionState.Ready);
        _presentationModel.PresentReadySnapshot(snapshot, () => SnapshotApplied?.Invoke(snapshot));
    }

    private void OnCanonicalApplied(NativeEnvelope envelope)
    {
        if (envelope.Kind == NativeMessageKind.Event)
        {
            ResolveFromCanonicalEvent(envelope);
        }
        PresentProjection();
    }

    private void OnMutationAuthorityChanged(bool available)
    {
        if (available)
        {
            RefreshMutationAvailability();
        }
        else
        {
            ClearWorkflowAuthority();
        }
    }

    private void TransitionTo(ConnectionState state)
    {
        _connectionState = state;
        RefreshMutationAvailability();
        _presentationModel.PresentConnection(ConnectionPresentation.Create(state));
        ConnectionStateChanged?.Invoke(state);
    }

    private void Fail(string errorCode)
    {
        _connectionState = ConnectionState.Failed;
        ClearWorkflowAuthority();
        _presentationModel.PresentConnection(ConnectionPresentation.Failed(errorCode));
        ConnectionStateChanged?.Invoke(ConnectionState.Failed);
    }
}
