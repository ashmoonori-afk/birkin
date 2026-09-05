using System.Collections.Frozen;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;

namespace Birkin.Native.Protocol.Transport;

public interface INativeClientConnection : IAsyncDisposable
{
    bool HasLiveCapability(DateTimeOffset now) => false;
    IReadOnlySet<string> AdvertisedCommands => FrozenSet<string>.Empty;
    bool OwnsReceiveLoop => false;
    NativeProjectionStore? ProjectionStore => null;
    Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion, CancellationToken cancellationToken);
    ValueTask SendCommandAsync(NativeCommandRequest request, CancellationToken cancellationToken) =>
        throw new NativeProtocolError("E_STATE", "connection does not support command submission");
    ValueTask<NativeEnvelope> SendCommandForResultAsync(
        NativeCommandRequest request,
        CancellationToken cancellationToken) =>
        throw new NativeProtocolError("E_STATE", "connection does not own command result correlation");
    ValueTask SwitchSessionAsync(string sessionId, CancellationToken cancellationToken) =>
        throw new NativeProtocolError("E_STATE", "connection does not support session switching");
    ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken);
}
