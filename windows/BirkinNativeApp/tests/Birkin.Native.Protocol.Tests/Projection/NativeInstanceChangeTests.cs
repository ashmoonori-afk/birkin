using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeInstanceChangeTests
{
    [TestMethod]
    public void Prepare_WhenReadyInstanceChanges_DiscardsProjectionAndSurfaceRevisionsBeforeSubscribe()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        var oldIdentity = new NativeReadyIdentity("session-1", "instance-1", "fixture-version");
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), oldIdentity);
        store.ApplySurface(DecodeSurface("browser_aside", 7, NativeMessageKind.SurfaceSnapshot));
        var changedIdentity = new NativeReadyIdentity("session-1", "instance-2", "fixture-version");

        // When
        var subscription = NativeReconnect.Prepare(store, changedIdentity);

        // Then
        Assert.IsNull(store.State);
        Assert.AreEqual(0, store.SurfaceRevisions.Count);
        Assert.IsTrue(subscription.IsCanonicalRepair);
        Assert.AreEqual(0L, subscription.AfterCursor);
        Assert.IsNull(subscription.KnownInstanceId);
        Assert.AreEqual(0, subscription.SurfaceRevisions.Count);
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
            new("payload", new NativeJsonObject()),
        ]));
        return NativeFrameCodec.Decode(NativeFrameCodec.Encode(envelope));
    }
}
