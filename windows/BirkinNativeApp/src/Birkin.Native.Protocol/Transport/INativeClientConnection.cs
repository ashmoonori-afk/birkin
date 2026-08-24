using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Transport;

public interface INativeClientConnection : IAsyncDisposable
{
    Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion, CancellationToken cancellationToken);
    ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken);
}
