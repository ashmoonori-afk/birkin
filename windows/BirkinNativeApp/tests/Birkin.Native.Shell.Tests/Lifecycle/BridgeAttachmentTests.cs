using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Lifecycle;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Lifecycle;

[TestClass]
public sealed class BridgeAttachmentTests
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";

    [TestMethod]
    public void AttachedExternal_WhenCreatedFromAnnouncement_PreservesDiagnosticIdentityWithoutOwnership()
    {
        // Given
        var announcement = BridgeAnnouncement.Parse(
            $$"""{"event":"listening","transport":"loopback","pid":27192,"root":"C:\\root","session_id":"session-1","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"C:\\root\\native\\endpoint.json"}""");

        // When
        var attachment = new BridgeAttachment.AttachedExternal(announcement);

        // Then
        Assert.AreSame(announcement, attachment.Announcement);
        Assert.AreEqual(27192, attachment.ProcessId);
    }
}
