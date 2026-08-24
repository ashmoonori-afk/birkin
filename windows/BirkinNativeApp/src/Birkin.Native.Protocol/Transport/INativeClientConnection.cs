using System.Collections.Frozen;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;

namespace Birkin.Native.Protocol.Transport;

public interface INativeClientConnection : IAsyncDisposable
{
    bool HasLiveCapability(DateTimeOffset now) => false;
    IReadOnlySet<string> AdvertisedCommands => FrozenSet<string>.Empty;
    Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion, CancellationToken cancellationToken);
    ValueTask SendCommandAsync(NativeCommandRequest request, CancellationToken cancellationToken) =>
        throw new NativeProtocolError("E_STATE", "connection does not support command submission");
    ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken);
}
