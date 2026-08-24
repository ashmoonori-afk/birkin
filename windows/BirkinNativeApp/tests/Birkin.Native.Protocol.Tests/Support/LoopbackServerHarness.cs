using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Tests.Support;

internal sealed class LoopbackServerHarness : IAsyncDisposable
{
    private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource _deadline = new(TimeSpan.FromSeconds(5));
    private readonly Task<TcpClient> _accepted;
    private TcpClient? _client;

    public LoopbackServerHarness()
    {
        _listener.Start();
        Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
        _accepted = _listener.AcceptTcpClientAsync(_deadline.Token).AsTask();
    }

    public int Port { get; }

    public async Task<NativeEnvelope> ReceiveAsync()
    {
        var stream = await GetStreamAsync().ConfigureAwait(false);
        var header = new byte[sizeof(uint)];
        await stream.ReadExactlyAsync(header, _deadline.Token).ConfigureAwait(false);
        var length = BinaryPrimitives.ReadUInt32BigEndian(header);
        if (length > NativeProtocolConstants.MaxFrameBytes)
        {
            throw new InvalidDataException("test server received an oversized frame");
        }

        var body = new byte[checked((int)length)];
        await stream.ReadExactlyAsync(body, _deadline.Token).ConfigureAwait(false);
        return NativeFrameCodec.Decode([.. header, .. body]);
    }

    public async Task SendAsync(NativeEnvelope envelope)
    {
        var stream = await GetStreamAsync().ConfigureAwait(false);
        await stream.WriteAsync(NativeFrameCodec.Encode(envelope), _deadline.Token).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        _deadline.Cancel();
        _listener.Dispose();
        if (_client is null)
        {
            try
            {
                _client = await _accepted.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
        _client?.Dispose();
        _deadline.Dispose();
    }

    private async Task<NetworkStream> GetStreamAsync()
    {
        _client ??= await _accepted.ConfigureAwait(false);
        return _client.GetStream();
    }
}
