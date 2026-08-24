using System.Windows.Controls;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class DiffViewTests
{
    [TestMethod]
    public async Task Projection_WhenDifferenceExists_ShowsBothMachineSentinelValuesBeforeApproval()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();

            // When
            var view = new DiffView(fixture.Model);
            OfficeWorkflowViewHarness.Layout(view);
            var items = OfficeWorkflowViewHarness.Find<ItemsControl>(view, "diff.items");
            var visible = string.Join("\n", items.Items.Cast<object>());

            // Then
            StringAssert.Contains(visible, "4100");
            StringAssert.Contains(visible, "4700");
            Assert.IsTrue(fixture.Model.Workspace!.Conversation.Any(row => row.Id == "approval-7"));
        });
    }
}
