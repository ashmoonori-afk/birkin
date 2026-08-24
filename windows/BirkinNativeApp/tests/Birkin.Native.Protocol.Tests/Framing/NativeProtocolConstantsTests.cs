using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Framing;

[TestClass]
public sealed class NativeProtocolConstantsTests
{
    [TestMethod]
    public void Constants_WhenComparedWithPythonFixture_AreIdentical()
    {
        // Given
        var vectors = GoldenVectorFixture.Load();

        // When
        var kinds = vectors.Select(vector => vector.Kind).ToHashSet(StringComparer.Ordinal);

        // Then
        Assert.AreEqual("birkin-local-1", NativeProtocolConstants.Name);
        Assert.AreEqual(1, NativeProtocolConstants.Version);
        Assert.AreEqual(262_144U, NativeProtocolConstants.MaxFrameBytes);
        Assert.AreEqual(12, NativeProtocolConstants.MaxBodyDepth);
        CollectionAssert.AreEquivalent(NativeMessageKind.All.Select(kind => kind.WireName).ToArray(), kinds.ToArray());
    }
}
