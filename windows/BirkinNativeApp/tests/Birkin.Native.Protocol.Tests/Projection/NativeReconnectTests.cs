using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeReconnectTests
{
    private static readonly NativeReadyIdentity ReadyIdentity = new("session-1", "instance-1", "fixture-version");

    [TestMethod]
    public void Prepare_WhenStoreIsEmpty_RequestsAuthoritativeOfficeProjection()
    {
        var subscription = NativeReconnect.Prepare(
            new NativeProjectionStore(),
            ReadyIdentity);

        Assert.IsTrue(subscription.IsCanonicalRepair);
        Assert.AreEqual(1, subscription.SurfaceRevisions.Count);
        Assert.AreEqual(0L, subscription.SurfaceRevisions["office"]);
    }

    [TestMethod]
    public void Prepare_WhenInstanceMatches_OffersOnlyContiguousCacheValuesAsReplayHints()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), ReadyIdentity);
        store.ApplyEvent(Decode(fixture.RootElement.GetProperty("events")[0]));
        store.ApplySurface(DecodeSurface("browser_aside", 2));

        // When
        var subscription = NativeReconnect.Prepare(store, ReadyIdentity);

        // Then
        Assert.IsFalse(subscription.IsCanonicalRepair);
        Assert.AreEqual(3L, subscription.AfterCursor);
        Assert.AreEqual("instance-1", subscription.KnownInstanceId);
        Assert.AreEqual(2L, subscription.SurfaceRevisions["browser_aside"]);
    }

    [TestMethod]
    public void ApplyStreamSignal_WhenDesynchronized_RequestsCanonicalRepairWithoutApplyingContent()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), ReadyIdentity);
        var previous = store.State;
        var signal = new NativeEnvelope(NativeMessageKind.StreamDesynchronized, "desync-1",
            new NativeJsonObject([new("resume_after", new NativeJsonInteger(9))]));

        // When
        store.ApplyStreamSignal(NativeFrameCodec.Decode(NativeFrameCodec.Encode(signal)));

        // Then
        Assert.AreSame(previous, store.State);
        Assert.AreEqual(NativeProjectionRepairReason.StreamDesynchronized, store.RepairReason);
        Assert.IsTrue(NativeReconnect.Prepare(store, ReadyIdentity).IsCanonicalRepair);
    }

    private static JsonDocument LoadFixture() => JsonDocument.Parse(File.ReadAllBytes(
        Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json")));

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));

    private static NativeEnvelope DecodeSurface(string name, long revision)
    {
        var envelope = new NativeEnvelope(NativeMessageKind.SurfaceSnapshot, $"surface-{revision}",
            new NativeJsonObject([
                new("surface", new NativeJsonString(name)),
                new("revision", new NativeJsonInteger(revision)),
                new("payload", new NativeJsonObject()),
            ]));
        return NativeFrameCodec.Decode(NativeFrameCodec.Encode(envelope));
    }
}
