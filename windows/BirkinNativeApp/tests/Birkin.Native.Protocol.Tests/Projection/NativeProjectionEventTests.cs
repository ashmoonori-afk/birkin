using System.Text;
using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeProjectionEventTests
{
    private static readonly NativeReadyIdentity ReadyIdentity = new("session-1", "instance-1", "fixture-version");

    [TestMethod]
    public void ApplyEvent_WhenPythonEventsAreContiguous_MatchesEveryExpectedProjection()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), ReadyIdentity);
        var consumed = 0;

        // When / Then
        foreach (var vector in fixture.RootElement.GetProperty("events").EnumerateArray())
        {
            store.ApplyEvent(Decode(vector));
            consumed++;

            var expected = NativeJsonParser.Parse(Encoding.UTF8.GetBytes(
                vector.GetProperty("expected_state").GetRawText()));
            var state = store.State;
            Assert.IsNotNull(state);
            var expectedBytes = NativeJsonSerializer.Serialize(expected);
            var actualBytes = NativeJsonSerializer.Serialize(StateJson(state));
            CollectionAssert.AreEqual(
                expectedBytes,
                actualBytes,
                $"cursor {vector.GetProperty("cursor").GetInt64()} "
                + FirstDifference(expectedBytes, actualBytes));
            Assert.AreEqual(vector.GetProperty("cursor").GetInt64(), state.Cursor);
            Assert.AreEqual(NativeProjectionStoreStatus.Current, store.Status);
        }

        Assert.AreEqual(19, consumed);
    }

    private static NativeJsonObject StateJson(NativeProjectionState state) => new([
        new("protocol_version", new NativeJsonInteger(state.ProtocolVersion)),
        new("session_id", new NativeJsonString(state.SessionId)),
        new("cursor", new NativeJsonInteger(state.Cursor)),
        new("panels", state.Panels),
        new("conversation", state.Conversation),
        new("composer", state.Composer),
        new("status", state.Status),
        new("working_memory", state.WorkingMemory),
        new("approval_policy", state.ApprovalPolicy),
        new("terminals", state.Terminals),
    ]);

    private static JsonDocument LoadFixture() => JsonDocument.Parse(File.ReadAllBytes(
        Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json")));

    private static string FirstDifference(byte[] expected, byte[] actual)
    {
        var index = Enumerable.Range(0, Math.Min(expected.Length, actual.Length))
            .FirstOrDefault(offset => expected[offset] != actual[offset], -1);
        if (index < 0)
        {
            return $"length expected={expected.Length} actual={actual.Length}";
        }
        var start = Math.Max(0, index - 48);
        var expectedCount = Math.Min(expected.Length - start, 96);
        var actualCount = Math.Min(actual.Length - start, 96);
        return $"difference={index} "
            + $"expected={Encoding.UTF8.GetString(expected, start, expectedCount)} "
            + $"actual={Encoding.UTF8.GetString(actual, start, actualCount)}";
    }

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));
}
