using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Presentation;
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

    [TestMethod]
    public async Task CanonicalDiffAndCorrelatedReceipt_WhenApplied_BindRowsAndApprovalStateTransition()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new DiffView(fixture.Model, fixture.Coordinator.ProjectionStore);
            OfficeWorkflowViewHarness.Layout(view, 340, 260);

            var normalized = Object(
                ("left", Nodes(("cell", 4, "4100"))),
                ("right", Nodes(("cell", 4, "4700"))));
            var diff = Object(
                ("diff_id", Text("diff-canonical")),
                ("semantic", Object(("normalized_ir", normalized))));
            fixture.ApplyCanonical("office.diff_ready", Object(
                ("result", Object(("diff", diff)))));
            await view.Dispatcher.InvokeAsync(view.UpdateLayout);

            var items = OfficeWorkflowViewHarness.Find<ItemsControl>(view, "diff.items");
            var row = items.Items.Cast<OfficeDiffRowPresentation>().Single();
            Assert.AreEqual("cell 4", row.Label);
            Assert.AreEqual("4100", row.OldValue);
            Assert.AreEqual("4700", row.NewValue);
            Assert.IsFalse(Descendants<TextBlock>(view).Any(text => text.Text.Contains("diff_id", StringComparison.Ordinal)));
            Assert.IsTrue(Descendants<TextBlock>(view).Any(text => text.Text == "4100"));
            Assert.IsTrue(Descendants<TextBlock>(view).Any(text => text.Text == "4700"));
            var state = OfficeWorkflowViewHarness.Find<TextBlock>(view, "diff.state");
            Assert.AreEqual("BEFORE APPROVAL", state.Text);

            fixture.ApplyCanonical("receipt.recorded", Object(
                ("diff_id", Text("diff-canonical")),
                ("approval_id", Text("approval-canonical")),
                ("artifact_id", Text("artifact-report"))));
            await view.Dispatcher.InvokeAsync(view.UpdateLayout);

            Assert.AreEqual("APPROVED", state.Text);
        });
    }

    private static NativeJsonString Text(string value) => new(value);

    private static NativeJsonArray Nodes(params (string Kind, long Order, string Value)[] nodes) =>
        new(nodes.Select(node => Object(
            ("kind", Text(node.Kind)),
            ("order", new NativeJsonInteger(node.Order)),
            ("text", Text(node.Value)))).ToArray());

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                yield return match;
            }
            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }
}
