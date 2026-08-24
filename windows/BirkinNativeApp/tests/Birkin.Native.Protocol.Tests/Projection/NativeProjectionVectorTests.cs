using System.Text;
using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeProjectionVectorTests
{
    [TestMethod]
    public void ApplySnapshot_WhenGivenPythonProjectionVector_MatchesEveryExpectedStateValue()
    {
        // Given
        var path = Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(path));
        var vector = fixture.RootElement.GetProperty("snapshot");
        var frame = Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!);
        var expected = (NativeJsonObject)NativeJsonParser.Parse(
            Encoding.UTF8.GetBytes(vector.GetProperty("expected_state").GetRawText()));
        var envelope = NativeFrameCodec.Decode(frame);
        var store = new NativeProjectionStore();

        // When
        store.ApplySnapshot(envelope, new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));

        // Then
        Assert.AreEqual("snapshot", vector.GetProperty("kind").GetString());
        Assert.AreEqual(vector.GetProperty("frame_byte_count").GetInt32(), frame.Length);
        var state = store.State;
        Assert.IsNotNull(state);
        AssertJsonEqual(expected["protocol_version"]!, new NativeJsonInteger(state.ProtocolVersion), "protocol_version");
        AssertJsonEqual(expected["session_id"]!, new NativeJsonString(state.SessionId), "session_id");
        AssertJsonEqual(expected["cursor"]!, new NativeJsonInteger(state.Cursor), "cursor");
        AssertJsonEqual(expected["panels"]!, state.Panels, "panels");
        AssertJsonEqual(expected["conversation"]!, state.Conversation, "conversation");
        AssertJsonEqual(expected["composer"]!, state.Composer, "composer");
        AssertJsonEqual(expected["status"]!, state.Status, "status");
        AssertJsonEqual(expected["working_memory"]!, state.WorkingMemory, "working_memory");
        AssertJsonEqual(expected["approval_policy"]!, state.ApprovalPolicy, "approval_policy");
        AssertJsonEqual(expected["terminals"]!, state.Terminals, "terminals");
        Assert.AreEqual("instance-1", state.InstanceId);
        Assert.AreEqual("initial", state.ResetReason);
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
