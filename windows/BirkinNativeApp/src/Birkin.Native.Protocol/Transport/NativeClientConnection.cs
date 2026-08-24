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

    public NativeClientConnection(NativeProjectionStore? projectionStore = null,
        Func<TimeSpan, CancellationToken, ValueTask>? delayAsync = null, Func<double>? jitter = null)
    {
        _projectionStore = projectionStore ?? new NativeProjectionStore();
        _delayAsync = delayAsync ?? ((delay, cancellationToken) => new(Task.Delay(delay, cancellationToken)));
        _jitter = jitter ?? Random.Shared.NextDouble;
    }

    public bool ContainsBootstrapSecretForTesting => _bootstrapSecret is not null;
    public bool IsProjectionCurrent { get; private set; }
    public NativeSessionCapability? CurrentCapability => Volatile.Read(ref _currentCapability);
    public NativeSessionCapability? PredecessorCapability => Volatile.Read(ref _predecessorCapability);

    public async Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        if (_transport is not null)
            throw new NativeProtocolError("E_STATE", "connection is already active");

        _announcement = announcement;
        _expectedProductVersion = expectedProductVersion;
        _reconnectAttempt = 0;
        await ConnectCoreAsync(announcement, expectedProductVersion, cancellationToken).ConfigureAwait(false);
    }

    public async ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            if (!_subscribed || _transport is null)
            {
                throw new NativeProtocolError("E_STATE", "connection is not subscribed");
            }

            NativeEnvelope envelope;
            try
            {
                envelope = await _transport.ReceiveAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (Exception error) when (
                error is IOException or SocketException && !cancellationToken.IsCancellationRequested)
            {
                await DisconnectAsync().ConfigureAwait(false);
                await ReconnectAsync(cancellationToken).ConfigureAwait(false);
                continue;
            }

            Claim(envelope.Id);
            NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
            if (envelope.Kind == NativeMessageKind.Ready)
                throw new NativeProtocolError("E_STATE", "ready is not valid after subscription");
            ValidateCommandCorrelation(envelope);
            await HandleLifecycleFrameAsync(envelope, cancellationToken).ConfigureAwait(false);
            return envelope;
        }
    }

    public async ValueTask DisposeAsync() => await DisconnectAsync().ConfigureAwait(false);

    public static TimeSpan ReconnectDelay(int attempt, double jitter)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(attempt);
        ArgumentOutOfRangeException.ThrowIfLessThan(jitter, 0);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(jitter, 1);
        var baseMilliseconds = attempt switch
        {
            0 => 250,
            1 => 500,
            2 => 1_000,
            3 => 2_000,
            _ => 5_000,
        };
        return TimeSpan.FromMilliseconds(baseMilliseconds * (0.8 + (0.4 * jitter)));
    }

    private async Task ConnectCoreAsync(BridgeAnnouncement announcement, string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        if (!string.Equals(expectedProductVersion, announcement.ServerVersion, StringComparison.Ordinal))
            throw new NativeProtocolError("E_VERSION_MISMATCH", "announcement and client product versions differ");

        lock (_idGate)
        {
            _seenIds.Clear();
            _idOrder.Clear();
        }
        var discovery = DiscoveryRecordReader.Read(announcement.DiscoveryPath, announcement, DateTimeOffset.UtcNow);
        _bootstrapSecret = discovery.TakeBootstrapSecret()
            ?? throw new NativeProtocolError("E_BOOTSTRAP_INVALID", "bootstrap secret has already been consumed");
        var transport = await LoopbackTransportConnection.ConnectAsync(discovery.Port, cancellationToken).ConfigureAwait(false);
        _transport = transport;
        try
        {
            var hello = NativeHandshake.CreateHello(expectedProductVersion, _bootstrapSecret, NextId());
            Claim(hello.Id);
            await transport.SendAsync(hello, cancellationToken).ConfigureAwait(false);
            var ready = await transport.ReceiveAsync(cancellationToken).ConfigureAwait(false);
            Claim(ready.Id);
            NativeReadySession session;
            try
            {
                session = NativeHandshake.ValidateReady(
                    ready,
                    new NativeHandshakeExpectation(hello.Id, expectedProductVersion, announcement));
            }
            finally
            {
                _bootstrapSecret = null;
            }

            var subscription = NativeReconnect.Prepare(_projectionStore, session.Identity);
            SetInitialCapability(session.SessionCapability);
            _session = session;
            var subscribe = NativeHandshake.CreateSubscribe(session, NextId(), subscription);
            Claim(subscribe.Id);
            await transport.SendAsync(subscribe, cancellationToken).ConfigureAwait(false);
            _subscribed = true;
            _reconnectAttempt = 0;
        }
        catch
        {
            _bootstrapSecret = null;
            _transport = null;
            ClearAuthority();
            await transport.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    private async Task HandleLifecycleFrameAsync(NativeEnvelope envelope, CancellationToken cancellationToken)
    {
        switch (envelope.Kind.WireName)
        {
            case "ping":
                var capability = CurrentCapability
                    ?? throw new NativeProtocolError("E_CAPABILITY_EXPIRED", "session capability is unavailable");
                var pong = NativeHandshake.CreatePong(envelope, capability, NextId());
                Claim(pong.Id);
                await (_transport ?? throw new NativeProtocolError("E_STATE", "connection is not active"))
                    .SendAsync(pong, cancellationToken).ConfigureAwait(false);
                break;
            case "capability.renewed":
                ReplaceCapability(NativeHandshake.ValidateRenewedCapability(envelope));
                break;
            case "stream.desynchronized":
                await RequestCanonicalRepairAsync(envelope, cancellationToken).ConfigureAwait(false);
                break;
            case "snapshot":
                IsProjectionCurrent = true;
                break;
            case "goodbye":
                await DisconnectAsync().ConfigureAwait(false);
                break;
            case "error":
                if (envelope.Body["code"] is NativeJsonString { Value: "E_CAPABILITY_EXPIRED" }) ClearAuthority();
                break;
            case "event":
            case "surface_snapshot":
            case "surface_event":
            case "receipt":
            case "pong":
                break;
            default:
                throw new NativeProtocolError("E_STATE", "server frame is not valid during a subscribed session");
        }
    }

    private async Task RequestCanonicalRepairAsync(NativeEnvelope envelope, CancellationToken cancellationToken)
    {
        _projectionStore.ApplyStreamSignal(envelope);
        IsProjectionCurrent = false;
        var session = _session ?? throw new NativeProtocolError("E_STATE", "connection session is unavailable");
        var resumeAfter = envelope.Body["resume_after"] is NativeJsonInteger cursor
            ? cursor.Value
            : throw new NativeProtocolError("E_BODY", "resume cursor is invalid");
        var revisions = _projectionStore.SurfaceRevisions.ToDictionary(
            pair => pair.Key,
            _ => 0L,
            StringComparer.Ordinal);
        var repair = new NativeProjectionSubscription(
            resumeAfter,
            session.InstanceId,
            revisions,
            isCanonicalRepair: true);
        var subscribe = NativeHandshake.CreateSubscribe(session, NextId(), repair);
        Claim(subscribe.Id);
        await (_transport ?? throw new NativeProtocolError("E_STATE", "connection is not active"))
            .SendAsync(subscribe, cancellationToken).ConfigureAwait(false);
    }

    private async Task ReconnectAsync(CancellationToken cancellationToken)
    {
        var announcement = _announcement
            ?? throw new NativeProtocolError("E_STATE", "reconnect announcement is unavailable");
        var expectedProductVersion = _expectedProductVersion
            ?? throw new NativeProtocolError("E_STATE", "reconnect version is unavailable");
        while (true)
        {
            await _delayAsync(ReconnectDelay(_reconnectAttempt, _jitter()), cancellationToken).ConfigureAwait(false);
            try
            {
                await ConnectCoreAsync(announcement, expectedProductVersion, cancellationToken).ConfigureAwait(false);
                return;
            }
            catch (Exception error) when (
                error is IOException or SocketException && !cancellationToken.IsCancellationRequested)
            {
                _reconnectAttempt++;
            }
        }
    }

    private async ValueTask DisconnectAsync()
    {
        _bootstrapSecret = null;
        _subscribed = false;
        _session = null;
        IsProjectionCurrent = false;
        ClearAuthority();
        var transport = _transport;
        _transport = null;
        if (transport is not null)
        {
            await transport.DisposeAsync().ConfigureAwait(false);
        }
    }

    private void SetInitialCapability(NativeSessionCapability capability)
    {
        lock (_capabilityGate) { _currentCapability = capability; _predecessorCapability = null; }
    }

    private void ReplaceCapability(NativeSessionCapability capability)
    {
        lock (_capabilityGate) { _predecessorCapability = _currentCapability; _currentCapability = capability; }
    }

    private void ClearAuthority()
    {
        lock (_capabilityGate) { _currentCapability = null; _predecessorCapability = null; }
        ClearPendingCommand();
    }

}
