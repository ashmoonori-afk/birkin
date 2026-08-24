using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Framing;

[TestClass]
public sealed class NativeNegativeGoldenVectorParityTests
{
    [TestMethod]
    [TestCategory("Conformance")]
    public void Decode_WhenGivenPythonInvalidVectors_RefusesEveryFrameWithExpectedCode()
    {
        // Given
        var path = Path.Combine(
            AppContext.BaseDirectory,
            "GoldenVectors",
            "native-protocol-invalid-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(path));
        Assert.AreEqual(1, fixture.RootElement.GetProperty("schema_version").GetInt32());
        var vectors = fixture.RootElement.GetProperty("vectors");
        Assert.AreEqual(20, vectors.GetArrayLength());

        // When / Then
        foreach (var vector in vectors.EnumerateArray())
        {
            var name = vector.GetProperty("name").GetString()!;
            var frame = Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!);
            var expectedCode = vector.GetProperty("expected_error_code").GetString();

            var error = Assert.ThrowsException<NativeProtocolError>(
                () => NativeFrameCodec.Decode(frame),
                name);
            Assert.AreEqual(expectedCode, error.Code, name);
        }
    }
}
