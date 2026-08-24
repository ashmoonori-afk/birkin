using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Transport;

public sealed class NativeClientConnection : INativeClientConnection
{
    private const int MaxTrackedFrameIds = 1_024;
    private readonly HashSet<string> _seenIds = new(StringComparer.Ordinal);
    private readonly Queue<string> _idOrder = new();
    private INativeTransportConnection? _transport;
    private string? _bootstrapSecret;
    private long _nextId;
    private bool _subscribed;

    public bool ContainsBootstrapSecretForTesting => _bootstrapSecret is not null;

    public async Task ConnectAsync(
        BridgeAnnouncement announcement,
        string expectedProductVersion,
        CancellationToken cancellationToken)
    {
        if (_transport is not null)
        {
            throw new NativeProtocolError("E_STATE", "connection is already active");
        }
        if (!string.Equals(expectedProductVersion, announcement.ServerVersion, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_VERSION_MISMATCH", "announcement and client product versions differ");
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

            var subscribe = NativeHandshake.CreateSubscribe(session, NextId());
            Claim(subscribe.Id);
            await transport.SendAsync(subscribe, cancellationToken).ConfigureAwait(false);
            _subscribed = true;
        }
        catch
        {
            _bootstrapSecret = null;
            _transport = null;
            await transport.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    public async ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
    {
        if (!_subscribed || _transport is null)
        {
            throw new NativeProtocolError("E_STATE", "connection is not subscribed");
        }

        var envelope = await _transport.ReceiveAsync(cancellationToken).ConfigureAwait(false);
        Claim(envelope.Id);
        NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Server);
        if (envelope.Kind == NativeMessageKind.Ready)
        {
            throw new NativeProtocolError("E_STATE", "ready is not valid after subscription");
        }
        if (envelope.InReplyTo is not null)
        {
            throw new NativeProtocolError("E_CORRELATION", "unsolicited server frame carries correlation");
        }
        return envelope;
    }

    public async ValueTask DisposeAsync()
    {
        _bootstrapSecret = null;
        _subscribed = false;
        if (_transport is not null)
        {
            await _transport.DisposeAsync().ConfigureAwait(false);
            _transport = null;
        }
    }

    private string NextId() => $"client-{Interlocked.Increment(ref _nextId)}";

    private void Claim(string id)
    {
        if (!_seenIds.Add(id))
        {
            throw new NativeProtocolError("E_DUPLICATE_FRAME_ID", "frame id was reused inside the connection replay window");
        }
        _idOrder.Enqueue(id);
        if (_idOrder.Count > MaxTrackedFrameIds)
        {
            _seenIds.Remove(_idOrder.Dequeue());
        }
    }
}
