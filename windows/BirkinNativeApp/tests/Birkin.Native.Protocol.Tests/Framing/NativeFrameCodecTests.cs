using System.Buffers.Binary;
using System.Text;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Framing;

[TestClass]
public sealed class NativeFrameCodecTests
{
    [DataTestMethod]
    [DataRow(new byte[] { 0, 0, 0 }, "E_FRAME_INCOMPLETE")]
    [DataRow(new byte[] { 0, 0, 0, 3, 123, 125 }, "E_FRAME_INCOMPLETE")]
    [DataRow(new byte[] { 0, 0, 0, 1, 123, 125 }, "E_FRAME_TRAILING_DATA")]
    public void Decode_WhenFrameIsNotComplete_RefusesWithStableCode(byte[] frame, string code)
    {
        // Given / When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(frame));

        // Then
        Assert.AreEqual(code, error.Code);
    }

    [TestMethod]
    public void Decode_WhenDeclaredBodyIsOversized_RefusesBeforeReadingBody()
    {
        // Given
        var frame = new byte[4];
        BinaryPrimitives.WriteUInt32BigEndian(frame, NativeProtocolConstants.MaxFrameBytes + 1U);

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(frame));

        // Then
        Assert.AreEqual("E_FRAME_TOO_LARGE", error.Code);
    }

    [TestMethod]
    public void Decode_WhenBodyIsInvalidUtf8_RefusesWithStableCode()
    {
        // Given
        var frame = new byte[] { 0, 0, 0, 1, 0xff };

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(frame));

        // Then
        Assert.AreEqual("E_INVALID_UTF8", error.Code);
    }

    [TestMethod]
    public void Decode_WhenGoldenFrameHasTrailingByte_RefusesWithStableCode()
    {
        // Given
        var source = GoldenVectorFixture.Load()[0].Frame;
        var frame = source.Append((byte)0x20).ToArray();

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(frame));

        // Then
        Assert.AreEqual("E_FRAME_TRAILING_DATA", error.Code);
    }

    [DataTestMethod]
    [DataRow(1.0, "1.0")]
    [DataRow(-0.0, "-0.0")]
    [DataRow(0.0001, "0.0001")]
    [DataRow(0.00001, "1e-05")]
    [DataRow(1e16, "1e+16")]
    [DataRow(1.7976931348623157e308, "1.7976931348623157e+308")]
    [DataRow(5e-324, "5e-324")]
    public void Format_WhenGivenFixtureFloat_UsesPythonSpelling(double value, string expected)
    {
        // Given / When
        var actual = PythonFloatFormat.Format(value);

        // Then
        Assert.AreEqual(expected, actual);
    }

    internal static byte[] Frame(string json)
    {
        var body = Encoding.UTF8.GetBytes(json);
        var frame = new byte[body.Length + 4];
        BinaryPrimitives.WriteInt32BigEndian(frame, body.Length);
        body.CopyTo(frame.AsSpan(4));
        return frame;
    }
}
