using System.IO;
using System.IO.Compression;
using System.Windows.Controls;
using Birkin.Native.App;
using Birkin.Native.App.Tests.Support;
using Birkin.Native.Protocol.Framing;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Journeys;

[TestClass]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeWorkflowJourneyTests
{
    [TestMethod]
    public async Task Window_WhenOfficeJourneyRuns_UsesProjectedDiffAndCoordinatorCommands()
    {
        // Given
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync();
            var window = new MainWindow(fixture.Model, fixture.Coordinator);
            var shell = OfficeWorkflowViewHarness.Snapshot(window);
            OfficeWorkflowViewHarness.Layout(shell);
            var draft = OfficeWorkflowViewHarness.Find<TextBox>(
                shell,
                "conversation.draft");
            draft.Text = "기준 파일과 후보 파일을 비교하고 보고서를 작성해 주세요.";

            // When
            OfficeWorkflowViewHarness.Find<Button>(
                shell,
                "conversation.send"
            ).RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));
            await fixture.ResolveLastAsync();
            OfficeWorkflowViewHarness.Layout(shell);
            OfficeWorkflowViewHarness.Find<Button>(
                shell,
                "approval.approve.approval-7"
            ).RaiseEvent(new System.Windows.RoutedEventArgs(Button.ClickEvent));

            // Then
            CollectionAssert.AreEqual(new[] { "chat.send", "approval.answer" }, fixture.Connection.Sent.Select(item => item.CommandType).ToArray());
            Assert.AreEqual("approval-7", ((NativeJsonString)fixture.Connection.Sent[1].Payload["approval_id"]!).Value);
            Assert.IsTrue(OfficeWorkflowViewHarness.Find<ItemsControl>(shell, "diff.items").Items.Cast<object>().Any(item => item.ToString()!.Contains("4100", StringComparison.Ordinal) && item.ToString()!.Contains("4700", StringComparison.Ordinal)));
            window.Close();
        });
    }

    [TestMethod]
    public void Fixtures_WhenOpened_AreRealOoxmlPackagesWithDeterministicSentinels()
    {
        // Given
        var root = Path.Combine(AppContext.BaseDirectory, "Fixtures", "Office");

        // When
        using var baseline = ZipFile.OpenRead(Path.Combine(root, "baseline.xlsx"));
        using var candidate = ZipFile.OpenRead(Path.Combine(root, "candidate.xlsx"));
        using var report = ZipFile.OpenRead(Path.Combine(root, "report-template.docx"));
        var baselineText = ReadXml(baseline);
        var candidateText = ReadXml(candidate);
        var reportText = ReadXml(report);

        // Then
        StringAssert.Contains(baselineText, "4100");
        StringAssert.Contains(candidateText, "4700");
        StringAssert.Contains(reportText, "BIRKIN_P3_03_DOCUMENT_SENTINEL");
    }

    private static string ReadXml(ZipArchive archive) =>
        string.Join("\n", archive.Entries.Where(entry => entry.FullName.EndsWith(".xml", StringComparison.Ordinal)).Select(entry =>
        {
            using var reader = new StreamReader(entry.Open());
            return reader.ReadToEnd();
        }));
}
