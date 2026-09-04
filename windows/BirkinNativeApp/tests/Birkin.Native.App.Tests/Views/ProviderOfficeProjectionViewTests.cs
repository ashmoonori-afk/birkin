using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ProviderOfficeProjectionViewTests : MainWindowTestBase
{
    [TestMethod]
    public async Task MainWindow_ProjectsCanonicalDiffApprovalAndArtifactIntoVisibleControls()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var journey = sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator) { Width = 1500, Height = 940 };
            window.Show();
            try
            {
                fixture.ApplyCanonical("office.diff_ready", Object(
                    ("surface", Text("office")),
                    ("result", Object(("diff", Object(
                        ("diff_id", Text("diff-canonical")),
                        ("left", Text("4100")),
                        ("right", Text("4700"))))))));
                fixture.ApplyCanonical("approval.requested", Object(
                    ("approval_id", Text("approval-canonical")),
                    ("summary", Text("Canonical approval")),
                    ("sealed", new NativeJsonBoolean(true))));
                fixture.ApplyCanonical("office.updated", Object(
                    ("surface", Text("office")),
                    ("result", Object(("artifact", Object(
                        ("artifact_id", Text("artifact-canonical")),
                        ("media_type", Text("application/vnd.openxmlformats-officedocument.wordprocessingml.document"))))))));
                await window.Dispatcher.InvokeAsync(window.UpdateLayout);

                Assert.AreEqual(Visibility.Visible,
                    OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "diff.landmark").Visibility);
                Assert.IsTrue(OfficeWorkflowViewHarness.Find<ItemsControl>(window, "diff.items")
                    .Items.Cast<object>().Any(item => item.ToString()!.Contains("4700", StringComparison.Ordinal)));
                var approve = OfficeWorkflowViewHarness.Find<Button>(
                    window,
                    "approval.approve.approval-canonical");
                Assert.AreEqual("approval-canonical", approve.Tag as string);
                Assert.IsTrue(OfficeWorkflowViewHarness.Find<ItemsControl>(window, "office.items")
                    .Items.Cast<object>().Any(item => item.ToString()!.Contains("artifact-canonical", StringComparison.Ordinal)));
            }
            finally
            {
                window.Close();
            }
        });
        await journey.WaitAsync(deadline.Token);
    }

    private static NativeJsonString Text(string value) => new(value);

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
