using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Transport;

public sealed class LoopbackTransportConnection : INativeTransportConnection
{
    private readonly TcpClient _client;
    private readonly NetworkStream _stream;

    private LoopbackTransportConnection(TcpClient client)
    {
        _client = client;
        _stream = client.GetStream();
        RemoteAddress = ((IPEndPoint)client.Client.RemoteEndPoint!).Address;
    }

    public IPAddress RemoteAddress { get; }

    public static async Task<LoopbackTransportConnection> ConnectAsync(int port, CancellationToken cancellationToken)
    {
        if (port is < 1 or > 65535)
        {
            throw new NativeProtocolError("E_PORT", "loopback port is outside the TCP range");
        }

        var client = new TcpClient(AddressFamily.InterNetwork);
        try
        {
            await client.ConnectAsync(IPAddress.Loopback, port, cancellationToken).ConfigureAwait(false);
            return new LoopbackTransportConnection(client);
        }
        catch
        {
            client.Dispose();
            throw;
        }
    }

    public async ValueTask SendAsync(NativeEnvelope envelope, CancellationToken cancellationToken)
    {
        await _stream.WriteAsync(NativeFrameCodec.Encode(envelope), cancellationToken).ConfigureAwait(false);
    }

    public async ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken)
    {
        var header = new byte[sizeof(uint)];
        await _stream.ReadExactlyAsync(header, cancellationToken).ConfigureAwait(false);
        var length = BinaryPrimitives.ReadUInt32BigEndian(header);
        if (length > NativeProtocolConstants.MaxFrameBytes)
        {
            throw new NativeProtocolError("E_FRAME_TOO_LARGE", "native frame exceeds limit");
        }

        var body = new byte[checked((int)length)];
        await _stream.ReadExactlyAsync(body, cancellationToken).ConfigureAwait(false);
        return NativeFrameCodec.Decode([.. header, .. body]);
    }

    public async ValueTask DisposeAsync()
    {
        await _stream.DisposeAsync().ConfigureAwait(false);
        _client.Dispose();
    }
}
