using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Framing;

[TestClass]
public sealed class NativeGoldenVectorParityTests
{
    [TestMethod]
    public void RoundTrip_WhenGivenPythonGoldenVectors_IsByteIdenticalForAllTwentyOne()
    {
        // Given
        var vectors = GoldenVectorFixture.Load();
        Assert.AreEqual(21, vectors.Count);

        // When / Then
        foreach (var vector in vectors)
        {
            var envelope = NativeFrameCodec.Decode(vector.Frame);
            Assert.AreEqual(vector.Kind, envelope.Kind.WireName, vector.Name);
            Assert.AreEqual(vector.FrameByteCount, vector.Frame.Length, vector.Name);
            AssertJsonEqual(vector.ExpectedEnvelope, envelope.ToJsonValue(), vector.Name);
            CollectionAssert.AreEqual(vector.Frame, NativeFrameCodec.Encode(envelope), vector.Name);
        }
    }

    private static void AssertJsonEqual(NativeJsonValue expected, NativeJsonValue actual, string path)
    {
        Assert.AreEqual(expected.Kind, actual.Kind, path);
        switch (expected)
        {
            case NativeJsonNull:
                return;
            case NativeJsonBoolean boolean:
                Assert.AreEqual(boolean.Value, ((NativeJsonBoolean)actual).Value, path);
                return;
            case NativeJsonInteger integer:
                Assert.AreEqual(integer.Value, ((NativeJsonInteger)actual).Value, path);
                return;
            case NativeJsonFloat number:
                Assert.AreEqual(number.Value, ((NativeJsonFloat)actual).Value, path);
                return;
            case NativeJsonString text:
                Assert.AreEqual(text.Value, ((NativeJsonString)actual).Value, path);
                return;
            case NativeJsonArray array:
                var actualArray = (NativeJsonArray)actual;
                Assert.AreEqual(array.Values.Count, actualArray.Values.Count, path);
                for (var index = 0; index < array.Values.Count; index++)
                {
                    AssertJsonEqual(array.Values[index], actualArray.Values[index], $"{path}[{index}]");
                }
                return;
            case NativeJsonObject obj:
                var actualObject = (NativeJsonObject)actual;
                CollectionAssert.AreEqual(obj.Keys.ToArray(), actualObject.Keys.ToArray(), path);
                foreach (var key in obj.Keys)
                {
                    AssertJsonEqual(obj[key]!, actualObject[key]!, $"{path}.{key}");
                }
                return;
            default:
                Assert.Fail($"Unknown JSON value at {path}");
                return;
        }
    }
}
