using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

/// <summary>Owns the sole receive loop for one subscribed bridge connection.</summary>
public sealed partial class BridgeSession : INativeClientConnection
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
    private int _shutdownRequested;
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

}
