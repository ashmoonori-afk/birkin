using System.Net;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
public sealed class LoopbackTransportConnectionTests
{
    [TestMethod]
    public async Task ConnectAndReceive_WhenServerUsesFragmentedFrame_ReadsExactly()
    {
        // Given
        await using var server = new LoopbackServerHarness();
        await using var connection = await LoopbackTransportConnection.ConnectAsync(server.Port, CancellationToken.None);
        var sent = new NativeEnvelope(NativeMessageKind.Hello, "client-1", new NativeJsonObject());

        // When
        await connection.SendAsync(sent, CancellationToken.None);
        var received = await server.ReceiveAsync();

        // Then
        Assert.AreEqual("client-1", received.Id);
        Assert.AreEqual(IPAddress.Loopback, connection.RemoteAddress);
    }

    [DataTestMethod]
    [DataRow(0)]
    [DataRow(65536)]
    public async Task Connect_WhenPortIsOutsideTcpRange_Refuses(int port)
    {
        // Given / When
        var error = await Assert.ThrowsExceptionAsync<NativeProtocolError>(() => LoopbackTransportConnection.ConnectAsync(port, CancellationToken.None));

        // Then
        Assert.AreEqual("E_PORT", error.Code);
    }
}
