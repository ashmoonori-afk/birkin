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

        Assert.AreEqual(22, consumed);
    }

    [TestMethod]
    public void ApplyEvent_WhenProgressHistoryGrows_BoundsActivityItems()
    {
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            Decode(fixture.RootElement.GetProperty("snapshot")),
            ReadyIdentity);

        for (var cursor = 3; cursor < 123; cursor++)
        {
            store.ApplyEvent(ProgressEvent(cursor));
        }

        var state = store.State;
        Assert.IsNotNull(state);
        var activity = state.Panels.Values
            .Cast<NativeJsonObject>()
            .Single(panel =>
                panel["key"] is NativeJsonString { Value: "activity_logs" });
        var items = activity["items"] as NativeJsonArray;
        Assert.IsNotNull(items);
        Assert.AreEqual(100, items.Values.Count);
        Assert.AreEqual(
            "progress-122",
            ((NativeJsonString)((NativeJsonObject)items.Values[^1])["summary"]!).Value);
        Assert.AreEqual(
            "pending",
            ((NativeJsonString)((NativeJsonObject)items.Values[^1])["ui_state"]!).Value);
    }

    [TestMethod]
    public void ApplyEvent_WhenOfficeProgressArrives_PreservesStageForWindowsActivity()
    {
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            Decode(fixture.RootElement.GetProperty("snapshot")),
            ReadyIdentity);

        store.ApplyEvent(OfficeProgressEvent(3));

        var state = store.State;
        Assert.IsNotNull(state);
        var activity = state.Panels.Values
            .Cast<NativeJsonObject>()
            .Single(panel =>
                panel["key"] is NativeJsonString { Value: "activity_logs" });
        var item = (NativeJsonObject)((NativeJsonArray)activity["items"]!).Values[^1];
        Assert.AreEqual(
            "validation",
            ((NativeJsonString)item["office_phase"]!).Value);
        Assert.AreEqual(
            "job-progress",
            ((NativeJsonString)item["job_id"]!).Value);
        Assert.AreEqual(
            "pending",
            ((NativeJsonString)item["ui_state"]!).Value);
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

    private static NativeEnvelope ProgressEvent(long cursor) => new(
        NativeMessageKind.Event,
        $"server-{cursor}",
        new NativeJsonObject([
            new("protocol_version", new NativeJsonInteger(1)),
            new("session_id", new NativeJsonString("session-1")),
            new("cursor", new NativeJsonInteger(cursor)),
            new("event_id", new NativeJsonString($"progress-{cursor}")),
            new("type", new NativeJsonString("progress.updated")),
            new("timestamp", new NativeJsonString("2026-08-29T00:00:00Z")),
            new("actor_id", new NativeJsonString("python:runtime")),
            new("command_id", new NativeJsonString("progress-command")),
            new("payload", new NativeJsonObject([
                new("summary", new NativeJsonString($"progress-{cursor}")),
                new("status", new NativeJsonString("working")),
                new("ui_state", new NativeJsonString(
                    cursor == 122 ? "UNTRUSTED" : "pending")),
            ])),
        ]));

    private static NativeEnvelope OfficeProgressEvent(long cursor) => new(
        NativeMessageKind.Event,
        $"server-{cursor}",
        new NativeJsonObject([
            new("protocol_version", new NativeJsonInteger(1)),
            new("session_id", new NativeJsonString("session-1")),
            new("cursor", new NativeJsonInteger(cursor)),
            new("event_id", new NativeJsonString($"office-progress-{cursor}")),
            new("type", new NativeJsonString("progress.updated")),
            new("timestamp", new NativeJsonString("2026-08-29T00:00:00Z")),
            new("actor_id", new NativeJsonString("python:runtime")),
            new("command_id", new NativeJsonString("office-command")),
            new("payload", new NativeJsonObject([
                new("progress_id", new NativeJsonString("office:job-progress")),
                new("runtime_event", new NativeJsonString("office.validation")),
                new("office_phase", new NativeJsonString("validation")),
                new("job_id", new NativeJsonString("job-progress")),
                new("summary", new NativeJsonString("validation-complete")),
                new("status", new NativeJsonString("working")),
                new("ui_state", new NativeJsonString("pending")),
            ])),
        ]));
}
