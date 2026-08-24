using System.Windows.Automation;
using System.Windows.Controls;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ApprovalViewTests
{
    [TestMethod]
    public async Task Approve_WhenProjectedApprovalIsVisible_SubmitsItsCanonicalIdOnce()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ApprovalView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var approve = OfficeWorkflowViewHarness.Find<Button>(view, "approval.approve");

            // When
            approve.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("approval.answer", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual("approval-7", ((NativeJsonString)fixture.Connection.Sent[0].Payload["approval_id"]!).Value);
            Assert.AreEqual("approve", ((NativeJsonString)fixture.Connection.Sent[0].Payload["decision"]!).Value);
            Assert.AreEqual("Approve requested operation", AutomationProperties.GetName(approve));
        });
    }
}
