using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Lifecycle;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Lifecycle;

[TestClass]
public sealed class BridgeAttachmentTests
{
    [TestMethod]
    public void AttachedExternal_WhenCreatedFromAnnouncement_PreservesDiagnosticIdentityWithoutOwnership()
    {
        // Given
        var announcement = BridgeAnnouncement.Parse(TestBridgeAnnouncement.Json(27192));

        // When
        var attachment = new BridgeAttachment.AttachedExternal(announcement);

        // Then
        Assert.AreSame(announcement, attachment.Announcement);
        Assert.AreEqual(27192, attachment.ProcessId);
    }
}
