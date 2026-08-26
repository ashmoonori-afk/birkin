using System.Net.Sockets;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public sealed partial class NativeClientConnection : INativeClientConnection
{
    private const int MaxTrackedFrameIds = 1_024;
    private readonly HashSet<string> _seenIds = new(StringComparer.Ordinal);
    private readonly Queue<string> _idOrder = new();
    private readonly object _capabilityGate = new();
    private readonly object _idGate = new();
    private readonly NativeProjectionStore _projectionStore;
    private readonly Func<TimeSpan, CancellationToken, ValueTask> _delayAsync;
    private readonly Func<double> _jitter;
    private INativeTransportConnection? _transport;
    private NativeReadySession? _session;
    private NativeSessionCapability? _currentCapability;
    private NativeSessionCapability? _predecessorCapability;
    private BridgeAnnouncement? _announcement;
    private string? _expectedProductVersion;
    private string? _bootstrapSecret;
    private long _nextId;
    private int _reconnectAttempt;
    private bool _subscribed;
    private bool _canonicalRepairManagedExternally;

    public NativeClientConnection(NativeProjectionStore? projectionStore = null, Func<TimeSpan, CancellationToken, ValueTask>? delayAsync = null, Func<double>? jitter = null)
    {
        _projectionStore = projectionStore ?? new NativeProjectionStore();
        _delayAsync = delayAsync ?? ((delay, cancellationToken) => new(Task.Delay(delay, cancellationToken)));
        _jitter = jitter ?? Random.Shared.NextDouble;
    }

    public bool ContainsBootstrapSecretForTesting => _bootstrapSecret is not null;
    public bool IsProjectionCurrent { get; private set; }
    public NativeProjectionStore ProjectionStore => _projectionStore;

    public event Action? AuthorityUnavailable;
    public event Action<NativeReadyIdentity>? SnapshotInFlight;
    public NativeSessionCapability? CurrentCapability => Volatile.Read(ref _currentCapability);
    public bool HasLiveCapability(DateTimeOffset now) => CurrentCapability is { } capability && capability.ExpiresAt > now && capability.HardExpiresAt > now;
    public IReadOnlySet<string> AdvertisedCommands => Volatile.Read(ref _session)?.AdvertisedCommands ?? System.Collections.Frozen.FrozenSet<string>.Empty;
    public NativeSessionCapability? PredecessorCapability => Volatile.Read(ref _predecessorCapability);

}
