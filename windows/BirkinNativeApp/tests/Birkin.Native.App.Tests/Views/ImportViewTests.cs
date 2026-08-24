using System.Windows.Automation;
using System.Windows.Controls;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class ImportViewTests
{
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
}
