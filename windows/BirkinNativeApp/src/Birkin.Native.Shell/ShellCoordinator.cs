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
    private readonly object _stateLock = new();
    private readonly Queue<PresentationUpdate> _presentationQueue = new();
    private ConnectionState _connectionState = ConnectionState.Disconnected;
    private NativeProjectionState? _projectionState;
    private bool _projectionAuthorityAvailable;
    private bool _isDrainingPresentations;
    private long _nextProjectionCallbackSequence;
    private long _lastAuthorityCallbackSequence;

    private sealed record ConnectionAuthority(bool IsLive, IReadOnlySet<string> AdvertisedCommands);

    private sealed record PresentationUpdate(
        ConnectionPresentation? Connection,
        WorkspaceSnapshotPresentation? Workspace,
        OfficeWorkflowPresentation Workflow,
        ConnectionState? ChangedConnectionState = null);

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
        var callbackSequence = ReserveProjectionCallbackSequence();
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _projectionState = state;
            if (callbackSequence > _lastAuthorityCallbackSequence)
            {
                _projectionAuthorityAvailable = true;
                _lastAuthorityCallbackSequence = callbackSequence;
            }
            _connectionState = ConnectionState.Ready;
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Create(ConnectionState.Ready),
                snapshot,
                _workflow,
                ConnectionState.Ready));
        }
        DrainPresentations(drain);
    }

    private void OnCanonicalApplied(NativeEnvelope envelope)
    {
        var callbackSequence = ReserveProjectionCallbackSequence();
        var state = _projectionStore.State;
        if (state is null)
        {
            return;
        }

        var projectionAuthorityAvailable = _projectionStore.IsMutationAuthorityAvailable;
        var snapshot = WorkspaceSnapshotPresentation.FromProjection(state, "loopback");
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _projectionState = state;
            if (callbackSequence > _lastAuthorityCallbackSequence)
            {
                _projectionAuthorityAvailable = projectionAuthorityAvailable;
                _lastAuthorityCallbackSequence = callbackSequence;
            }
            if (envelope.Kind == NativeMessageKind.Event)
            {
                ResolveFromCanonicalEventLocked(envelope);
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, snapshot, _workflow));
        }
        DrainPresentations(drain);
    }

    private void OnMutationAuthorityChanged(bool available)
    {
        var callbackSequence = ReserveProjectionCallbackSequence();
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            if (callbackSequence <= _lastAuthorityCallbackSequence)
            {
                return;
            }

            _lastAuthorityCallbackSequence = callbackSequence;
            _projectionAuthorityAvailable = available;
            if (available)
            {
                RefreshMutationAvailabilityLocked(authority);
            }
            else
            {
                ClearWorkflowAuthorityLocked();
            }
            drain = EnqueuePresentationLocked(new(null, null, _workflow));
        }
        DrainPresentations(drain);
    }

    private void TransitionTo(ConnectionState state)
    {
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            _connectionState = state;
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Create(state),
                null,
                _workflow,
                state));
        }
        DrainPresentations(drain);
    }

    private void Fail(string errorCode)
    {
        bool drain;
        lock (_stateLock)
        {
            _connectionState = ConnectionState.Failed;
            ClearWorkflowAuthorityLocked();
            drain = EnqueuePresentationLocked(new(
                ConnectionPresentation.Failed(errorCode),
                null,
                _workflow,
                ConnectionState.Failed));
        }
        DrainPresentations(drain);
    }

    private ConnectionAuthority CaptureConnectionAuthority() => new(
        _connection.HasLiveCapability(DateTimeOffset.UtcNow),
        new HashSet<string>(_connection.AdvertisedCommands, StringComparer.Ordinal));

    private long ReserveProjectionCallbackSequence()
    {
        lock (_stateLock)
        {
            return ++_nextProjectionCallbackSequence;
        }
    }

    private bool EnqueuePresentationLocked(PresentationUpdate update)
    {
        _presentationQueue.Enqueue(update);
        if (_isDrainingPresentations)
        {
            return false;
        }

        _isDrainingPresentations = true;
        return true;
    }

    private void DrainPresentations(bool drain)
    {
        if (!drain)
        {
            return;
        }

        while (true)
        {
            PresentationUpdate update;
            lock (_stateLock)
            {
                if (!_presentationQueue.TryDequeue(out update!))
                {
                    _isDrainingPresentations = false;
                    return;
                }
            }

            Publish(update);
        }
    }

    private void Publish(PresentationUpdate update)
    {
        if (update.Workspace is { } workspace)
        {
            Action published = () => SnapshotApplied?.Invoke(workspace);
            if (update.Connection is { } readyConnection)
            {
                _presentationModel.PresentReadySnapshot(
                    readyConnection,
                    workspace,
                    update.Workflow,
                    published);
            }
            else
            {
                _presentationModel.PresentSnapshot(workspace, update.Workflow, published);
            }
        }
        else if (update.Connection is { } connection)
        {
            _presentationModel.PresentConnection(connection, update.Workflow);
        }
        else
        {
            _presentationModel.PresentOfficeWorkflow(update.Workflow);
        }

        if (update.ChangedConnectionState is { } state)
        {
            ConnectionStateChanged?.Invoke(state);
        }
    }
}
