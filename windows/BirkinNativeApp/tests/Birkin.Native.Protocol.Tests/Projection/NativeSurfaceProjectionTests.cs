using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeSurfaceProjectionTests
{
    [TestMethod]
    public void ApplySurface_WhenRevisionSkips_DiscardsSurfaceAndRequestsFullSurfaceSnapshot()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")),
            new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));
        store.ApplySurface(DecodeSurface("browser_aside", 1, NativeMessageKind.SurfaceSnapshot));

        // When
        store.ApplySurface(DecodeSurface("browser_aside", 3, NativeMessageKind.SurfaceEvent));

        // Then
        Assert.IsNull(store.Surface("browser_aside"));
        Assert.AreEqual(0L, store.SurfaceRevisions["browser_aside"]);
        Assert.AreEqual(NativeProjectionStoreStatus.RepairRequired, store.Status);
        Assert.AreEqual(NativeProjectionRepairReason.SurfaceGap, store.RepairReason);
        var subscription = NativeReconnect.Prepare(store,
            new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));
        Assert.AreEqual(0L, subscription.AfterCursor);
        Assert.AreEqual(0L, subscription.SurfaceRevisions["browser_aside"]);
    }

    private static JsonDocument LoadFixture() => JsonDocument.Parse(File.ReadAllBytes(
        Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json")));

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));

    private static NativeEnvelope DecodeSurface(string name, long revision, NativeMessageKind kind)
    {
        var envelope = new NativeEnvelope(kind, $"surface-{revision}", new NativeJsonObject([
            new("surface", new NativeJsonString(name)),
            new("revision", new NativeJsonInteger(revision)),
            new("payload", new NativeJsonObject([new("revision_marker", new NativeJsonInteger(revision))])),
        ]));
        return NativeFrameCodec.Decode(NativeFrameCodec.Encode(envelope));
    }
}
