using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Framing;

[TestClass]
public sealed class NativeEnvelopeStrictnessTests
{
    [DataTestMethod]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{},\"extra\":0}", "E_ENVELOPE_KEYS")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"body\":{}}", "E_ENVELOPE_KEYS")]
    [DataRow("{\"protocol\":\"other\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{}}", "E_PROTOCOL")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":true,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{}}", "E_PROTOCOL_VERSION")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":2,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{}}", "E_PROTOCOL_VERSION")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"invented\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{}}", "E_KIND")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"has space\",\"in_reply_to\":null,\"body\":{}}", "E_IDENTIFIER")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":[]}", "E_JSON")]
    public void Decode_WhenEnvelopeContractIsBroken_RefusesWithStableCode(string json, string code)
    {
        // Given / When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(NativeFrameCodecTests.Frame(json)));

        // Then
        Assert.AreEqual(code, error.Code);
    }

    [DataTestMethod]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"kind\":\"pong\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{}}", "E_DUPLICATE_KEY")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{\"n\":NaN}}", "E_NONFINITE_NUMBER")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{\"n\":9223372036854775808}}", "E_JSON")]
    [DataRow("{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"x\",\"in_reply_to\":null,\"body\":{\"s\":\"\\ud800\"}}", "E_JSON")]
    public void Decode_WhenJsonIsOutsideStrictSubset_RefusesWithStableCode(string json, string code)
    {
        // Given / When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(NativeFrameCodecTests.Frame(json)));

        // Then
        Assert.AreEqual(code, error.Code);
    }

    [TestMethod]
    public void Decode_WhenBodyExceedsDepthTwelve_RefusesWithStableCode()
    {
        // Given
        var body = "{}";
        for (var index = 0; index < NativeProtocolConstants.MaxBodyDepth; index++)
        {
            body = $"{{\"child\":{body}}}";
        }
        var json = $"{{\"protocol\":\"birkin-local-1\",\"protocol_version\":1,\"kind\":\"ping\",\"id\":\"deep\",\"in_reply_to\":null,\"body\":{body}}}";

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeFrameCodec.Decode(NativeFrameCodecTests.Frame(json)));

        // Then
        Assert.AreEqual("E_JSON_DEPTH", error.Code);
    }

    [TestMethod]
    public void Validate_WhenKindComesFromWrongEndpoint_RefusesWithStableCode()
    {
        // Given
        var envelope = new NativeEnvelope(NativeMessageKind.Ready, "ready-1", new NativeJsonObject());

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Client));

        // Then
        Assert.AreEqual("E_DIRECTION", error.Code);
    }

    [TestMethod]
    public void Validate_WhenHelloBodyKeysAreNotExact_RefusesWithStableCode()
    {
        // Given
        var envelope = new NativeEnvelope(NativeMessageKind.Hello, "hello-1", new NativeJsonObject());

        // When
        var error = Assert.ThrowsException<NativeProtocolError>(() => NativeBodyValidator.Validate(envelope, NativeMessageOrigin.Client));

        // Then
        Assert.AreEqual("E_BODY", error.Code);
    }
}
