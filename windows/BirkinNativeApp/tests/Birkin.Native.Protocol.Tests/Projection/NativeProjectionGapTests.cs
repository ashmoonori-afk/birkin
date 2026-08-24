using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeProjectionGapTests
{
    private static readonly NativeReadyIdentity ReadyIdentity = new("session-1", "instance-1", "fixture-version");

    [TestMethod]
    public void ApplyEvent_WhenPythonGapEventSkipsCursor_KeepsStaleStateAndRequestsCanonicalRepair()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), ReadyIdentity);
        foreach (var vector in fixture.RootElement.GetProperty("events").EnumerateArray())
        {
            store.ApplyEvent(Decode(vector));
        }
        var previous = store.State;

        // When
        store.ApplyEvent(Decode(fixture.RootElement.GetProperty("gap_event")));

        // Then
        Assert.AreSame(previous, store.State);
        Assert.AreEqual(16L, store.State!.Cursor);
        Assert.AreEqual(NativeProjectionStoreStatus.RepairRequired, store.Status);
        Assert.AreEqual(NativeProjectionRepairReason.CursorGap, store.RepairReason);
        var replay = NativeReconnect.Prepare(store, ReadyIdentity);
        Assert.IsTrue(replay.IsCanonicalRepair);
        Assert.AreEqual(0L, replay.AfterCursor);
        Assert.IsNull(replay.KnownInstanceId);
    }

    private static JsonDocument LoadFixture() => JsonDocument.Parse(File.ReadAllBytes(
        Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json")));

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));
}
