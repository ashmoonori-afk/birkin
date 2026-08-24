using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Transport;

public interface INativeTransportConnection : IAsyncDisposable
{
    ValueTask SendAsync(NativeEnvelope envelope, CancellationToken cancellationToken);
    ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken);
}
