using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ImportViewTests
{
    [TestMethod]
    public async Task Browse_WhenFileIsChosen_SelectsPathWithoutReadingFile()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var selected = @"C:\fixtures\first-report.xlsx";
            var view = new ImportView(
                fixture.Model,
                fixture.Coordinator,
                new StubOfficeFilePicker(selected));
            OfficeWorkflowViewHarness.Layout(view);
            var browse = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "import.browse");
            var path = OfficeWorkflowViewHarness.Find<TextBox>(
                view,
                "import.path");

            browse.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            Assert.AreEqual(selected, path.Text);
            Assert.AreEqual(0, fixture.Connection.Sent.Count);
        });
    }

    [TestMethod]
    public async Task Drop_WhenSingleSupportedPathIsMissing_StillDelegatesReadingToPython()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ImportView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var missing = @"C:\does-not-exist\first-report.docx";

            var submitted = await view.ImportDroppedFilesAsync([missing]);

            Assert.IsTrue(submitted);
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual(
                missing,
                ((NativeJsonString)fixture.Connection.Sent[0]
                    .Payload["source_path"]!).Value);
        });
    }

    [TestMethod]
    public async Task Drop_WhenSeveralPathsAreSelected_ShowsInlineStatusAndSendsNothing()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ImportView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var status = OfficeWorkflowViewHarness.Find<TextBlock>(
                view,
                "import.status");

            var submitted = await view.ImportDroppedFilesAsync(
                [
                    @"C:\fixtures\baseline.xlsx",
                    @"C:\fixtures\candidate.xlsx",
                ]);

            Assert.IsFalse(submitted);
            Assert.AreEqual(0, fixture.Connection.Sent.Count);
            Assert.AreEqual(System.Windows.Visibility.Visible, status.Visibility);
            Assert.IsFalse(string.IsNullOrWhiteSpace(status.Text));
            Assert.AreEqual(
                AutomationLiveSetting.Assertive,
                AutomationProperties.GetLiveSetting(status));
        });
    }

    [TestMethod]
    public async Task Import_WhenReceiptReturnsJailedReference_RendersNamedChip()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            fixture.Connection.NextImportReference = new ImportedFilePresentation(
                "import-1",
                "first-report.xlsx",
                "import-1.xlsx",
                new string('a', 64),
                1200);
            var view = new ImportView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var path = OfficeWorkflowViewHarness.Find<TextBox>(
                view,
                "import.path");
            var submit = OfficeWorkflowViewHarness.Find<Button>(
                view,
                "import.submit");
            path.Text = @"C:\fixtures\first-report.xlsx";

            submit.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));
            view.UpdateLayout();

            var chips = OfficeWorkflowViewHarness.FindAll<Border>(
                view,
                "import.chip");
            Assert.AreEqual(1, chips.Count);
            StringAssert.Contains(
                AutomationProperties.GetName(chips[0]),
                "first-report.xlsx");
        });
    }

    [TestMethod]
    public async Task Import_WhenPathSelected_SubmitsPathWithoutReadingFile()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var view = new ImportView(fixture.Model, fixture.Coordinator);
            OfficeWorkflowViewHarness.Layout(view);
            var path = OfficeWorkflowViewHarness.Find<TextBox>(view, "import.path");
            var submit = OfficeWorkflowViewHarness.Find<Button>(view, "import.submit");
            path.Text = @"C:\fixtures\baseline.xlsx";

            // When
            submit.RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            Assert.AreEqual(1, fixture.Connection.Sent.Count);
            Assert.AreEqual("file.import", fixture.Connection.Sent[0].CommandType);
            Assert.AreEqual(path.Text, ((NativeJsonString)fixture.Connection.Sent[0].Payload["source_path"]!).Value);
            Assert.AreEqual("Import selected office file", AutomationProperties.GetName(submit));
        });
    }

    private sealed class StubOfficeFilePicker(string selectedPath)
        : IOfficeFilePicker
    {
        public string? SelectOfficeFile(Window? owner) => selectedPath;
    }
}
