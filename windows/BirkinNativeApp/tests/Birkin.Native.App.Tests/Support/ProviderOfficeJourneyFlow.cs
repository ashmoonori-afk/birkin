using System.IO;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal sealed record ProviderOfficeFlowResult(int ProviderInvocations);

internal static class ProviderOfficeJourneyFlow
{
    public static async Task<ProviderOfficeFlowResult> RunAsync(
        string repositoryRoot,
        string temporaryRoot,
        CompositionRoot composition,
        ProviderOfficeEvidence evidence,
        string evidenceRoot,
        bool invokeProvider,
        CancellationToken cancellationToken)
    {
        var fixtureRoot = Path.Combine(repositoryRoot,
            "windows", "BirkinNativeApp", "tests", "Birkin.Native.App.Tests", "Fixtures", "Office");
        var window = new MainWindow(composition.PresentationModel, composition.Coordinator)
        {
            Width = 1500,
            Height = 940,
            WindowStartupLocation = WindowStartupLocation.Manual,
            Left = 24,
            Top = 24,
        };
        window.Show();
        window.Activate();
        window.UpdateLayout();
        using var events = new ProviderOfficeEventLog(composition.ProjectionStore);
        try
        {
            var artifacts = await ImportFixturesAsync(
                fixtureRoot, composition, window, events, evidence, cancellationToken);
            var draftBox = OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft");
            var send = OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send");
            Assert.IsTrue(draftBox.IsVisible, "the visible Conversation composer was not reachable");
            Assert.IsTrue(send.IsVisible && send.IsEnabled, "the visible Conversation Send action was not reachable");
            ProviderOfficeCommandTrace? chat = null;
            if (invokeProvider)
            {
                chat = await ProviderOfficeProviderTurn.SendAsync(
                    composition, window, events, evidence, cancellationToken);
            }

            var compare = await ProviderOfficeJourneyActions.SubmitAsync(
                composition.PresentationModel,
                events,
                "office.compare",
                () => composition.Coordinator.CompareOfficeDocumentsAsync(
                    new OfficeCompareIntent(
                        String(artifacts["baseline.xlsx"], "artifact_id"),
                        String(artifacts["candidate.xlsx"], "artifact_id")),
                    cancellationToken),
                cancellationToken);
            var diffEvent = await events.WaitAsync("office.diff_ready", compare.CommandId, cancellationToken);
            var diff = Object(Object(Payload(diffEvent), "result"), "diff");
            var diffId = String(diff, "diff_id");
            ProviderOfficeJourneyAssertions.AssertDeterministicDiff(artifacts, diff, diffId);
            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            var diffView = OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "diff.landmark");
            var diffItems = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "diff.items");
            Assert.AreEqual(Visibility.Visible, diffView.Visibility);
            var canonicalChange = diffItems.Items.Cast<Birkin.Native.Shell.Presentation.OfficeDiffRowPresentation>()
                .First(row => row.OldValue.Contains("4100", StringComparison.Ordinal)
                    && row.NewValue.Contains("4700", StringComparison.Ordinal));
            Assert.IsFalse(string.IsNullOrWhiteSpace(canonicalChange.Label));

            const string outputName = "comparison-report.docx";
            var outputPath = Path.Combine(
                temporaryRoot, "workspace", "office", "artifacts", "drafts", outputName);
            var draft = await ProviderOfficeJourneyActions.SubmitAsync(
                composition.PresentationModel,
                events,
                "office.draft",
                () => composition.Coordinator.DraftOfficeDocumentAsync(
                    new OfficeDraftIntent(
                        String(artifacts["report-template.docx"], "artifact_id"), diffId, outputName),
                    cancellationToken),
                cancellationToken);
            var requested = await events.WaitAsync("approval.requested", draft.CommandId, cancellationToken);
            var requestedPayload = Payload(requested);
            var approvalId = String(requestedPayload, "approval_id");
            var draftId = String(requestedPayload, "draft_id");
            Assert.AreEqual(diffId, String(requestedPayload, "diff_id"));
            Assert.IsTrue(Boolean(requestedPayload, "sealed"));
            Assert.IsFalse(File.Exists(outputPath), "output existed before visible approval");

            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            var outerContext = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "context.scroll");
            var officeScroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "office.workflow-scroll");
            var activityScroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "activity.scroll");
            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "outer context rail moved before Office interaction");
            diffView.BringIntoView();
            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "Office diff moved the outer context rail");
            var oldValue = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "diff.old-value")
                .First(text => text.Text.Contains("4100", StringComparison.Ordinal));
            var newValue = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "diff.new-value")
                .First(text => text.Text.Contains("4700", StringComparison.Ordinal));
            var diffBounds = diffView.TransformToAncestor(officeScroll).TransformBounds(
                new Rect(new Point(0, 0), diffView.RenderSize));
            var officeViewport = new Rect(new Point(0, 0), officeScroll.RenderSize);
            Assert.IsTrue(diffView.IsVisible && diffBounds.IntersectsWith(officeViewport),
                "the Python diff did not intersect the Office inner viewport");
            Assert.IsTrue(ProviderOfficeJourneyGeometry.IsInViewport(oldValue, officeScroll) && ProviderOfficeJourneyGeometry.IsInViewport(newValue, officeScroll),
                "the labeled 4100 -> 4700 controls were not visible in the Office inner viewport");
            var beforePath = Path.Combine(evidenceRoot, "pre-approval-diff-1500x940.png");
            var before = ProviderOfficeScreenshot.CaptureRedacted(window, beforePath, 1500, 940);
            evidence.Record("pre-approval-screenshot", new Dictionary<string, object?>
            {
                ["diff_id"] = diffId,
                ["cursor"] = Cursor(requested),
                ["png_sha256"] = before.Sha256,
                ["width"] = before.Width,
                ["height"] = before.Height,
            });

            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "pre-approval capture moved the outer context rail");
            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            var approve = OfficeWorkflowViewHarness.FindAll<Button>(window, "approval.approve")
                .Single(button => string.Equals(button.Tag as string, approvalId, StringComparison.Ordinal));
            Assert.IsTrue(approve.IsEnabled);
            var approvals = OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "approvals.landmark");
            Assert.IsTrue(ProviderOfficeJourneyGeometry.IsInViewport(approve, approvals), "the exact projected approval was not visibly actionable");
            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "approval interaction moved the outer context rail");
            var approval = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events, approve, "approval.answer", cancellationToken);
            var receiptEvent = await events.WaitAsync("receipt.recorded", approval.CommandId, cancellationToken);
            var savedEvent = await events.WaitAsync("office.updated", approval.CommandId, cancellationToken);
            var saved = Object(Object(Payload(savedEvent), "result"), "artifact");
            Assert.AreEqual(Path.GetFullPath(outputPath), Path.GetFullPath(String(saved, "uri")));
            ProviderOfficeJourneyAssertions.AssertReceiptCorrelation(
                Payload(receiptEvent), approvalId, String(saved, "artifact_id"), draftId,
                diffId, draft.CommandId, approval.CommandId);

            ProviderOfficePackageAssertions.AssertSpreadsheet(Path.Combine(fixtureRoot, "baseline.xlsx"), "4100");
            ProviderOfficePackageAssertions.AssertSpreadsheet(Path.Combine(fixtureRoot, "candidate.xlsx"), "4700");
            ProviderOfficePackageAssertions.AssertReport(outputPath);

            var open = await ProviderOfficeJourneyActions.SubmitAsync(
                composition.PresentationModel,
                events,
                "office.open",
                () => composition.Coordinator.OpenOfficeDocumentAsync(new OfficeOpenIntent(Artifact(saved)), cancellationToken),
                cancellationToken);
            var openedEvent = await events.WaitAsync("office.updated", open.CommandId, cancellationToken);
            var document = Object(Object(Payload(openedEvent), "result"), "document");
            Assert.AreEqual(String(saved, "content_hash"), String(Object(document, "source"), "sha256"));

            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            var savedArtifactId = String(saved, "artifact_id");
            ProviderOfficeJourneyAssertions.AssertActivityAndOfficeUi(window, savedArtifactId);
            var receiptTraces = new ProviderOfficeCommandTrace?[] { chat, draft, approval }
                .OfType<ProviderOfficeCommandTrace>().ToArray();
            ProviderOfficeJourneyAssertions.AssertStoredReceipts(temporaryRoot, receiptTraces, evidence);
            var savedActivity = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "activity.summary")
                .Single(text => text.Text == "Approved Office report saved and structurally verified");
            var savedReport = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "office.document-summary")
                .Single(text => text.Text == outputName);
            savedActivity.BringIntoView();
            savedReport.BringIntoView();
            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            Assert.IsTrue(ProviderOfficeJourneyGeometry.IsInViewport(savedActivity, activityScroll), "the report-saved Activity entry was clipped");
            Assert.IsTrue(ProviderOfficeJourneyGeometry.IsInViewport(savedReport, officeScroll), "the saved report artifact was clipped");
            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "inner list scrolling moved the outer context rail");
            var afterPath = Path.Combine(evidenceRoot, "post-save-activity-office-1500x940.png");
            var after = ProviderOfficeScreenshot.CaptureRedacted(window, afterPath, 1500, 940);
            evidence.Record("post-save-screenshot", new Dictionary<string, object?>
            {
                ["approval_id"] = approvalId,
                ["artifact_id"] = savedArtifactId,
                ["receipt_cursor"] = Cursor(receiptEvent),
                ["png_sha256"] = after.Sha256,
                ["width"] = after.Width,
                ["height"] = after.Height,
            });

            savedReport.BringIntoView();
            await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
            var constrainedPath = Path.Combine(evidenceRoot, "post-save-office-1100x700.png");
            var constrained = ProviderOfficeScreenshot.CaptureRedacted(
                window, constrainedPath, 1100, 700, savedReport.BringIntoView);
            Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "constrained Office capture moved the outer context rail");
            evidence.Record("constrained-post-save-screenshot", new Dictionary<string, object?>
            {
                ["artifact_id"] = savedArtifactId,
                ["cursor"] = Cursor(openedEvent),
                ["png_sha256"] = constrained.Sha256,
                ["width"] = constrained.Width,
                ["height"] = constrained.Height,
            });
            var providerInvocations = events.Events.Count(envelope =>
                ProviderOfficeEventLog.Type(envelope) == "message.user");
            Assert.AreEqual(invokeProvider ? 1 : 0, providerInvocations);
            return new ProviderOfficeFlowResult(providerInvocations);
        }
        finally
        {
            window.Close();
        }
    }

    private static async Task<Dictionary<string, NativeJsonObject>> ImportFixturesAsync(
        string fixtureRoot,
        CompositionRoot composition,
        Window window,
        ProviderOfficeEventLog events,
        ProviderOfficeEvidence evidence,
        CancellationToken cancellationToken)
    {
        var outerContext = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "context.scroll");
        var officeScroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "office.workflow-scroll");
        Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "outer context rail moved before import");
        var importPanel = OfficeWorkflowViewHarness.Find<Expander>(window, "office.import-panel");
        importPanel.BringIntoView();
        importPanel.IsExpanded = true;
        await ProviderOfficeJourneyGeometry.RenderBarrierAsync(window);
        Assert.IsTrue(ProviderOfficeJourneyGeometry.IsInViewport(importPanel, officeScroll), "Office import controls are outside the inner viewport");
        Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "import controls moved the outer context rail");
        var pathBox = OfficeWorkflowViewHarness.Find<TextBox>(window, "import.path");
        var import = OfficeWorkflowViewHarness.Find<Button>(window, "import.submit");
        var artifacts = new Dictionary<string, NativeJsonObject>(StringComparer.Ordinal);
        foreach (var name in new[] { "baseline.xlsx", "candidate.xlsx", "report-template.docx" })
        {
            pathBox.Text = Path.Combine(fixtureRoot, name);
            var trace = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events, import, "file.import", cancellationToken);
            var updated = await events.WaitAsync("office.updated", trace.CommandId, cancellationToken);
            var artifact = Object(Object(Payload(updated), "result"), "artifact");
            artifacts[name] = artifact;
            evidence.Record("import", new Dictionary<string, object?>
            {
                ["command_id"] = trace.CommandId,
                ["cursor"] = Cursor(updated),
                ["artifact_id"] = String(artifact, "artifact_id"),
                ["content_hash"] = String(artifact, "content_hash"),
            });
        }
        Assert.AreEqual(0d, outerContext.VerticalOffset, 0.1, "Office imports moved the outer context rail");
        return artifacts;
    }

    private static OfficeArtifact Artifact(NativeJsonObject value) => new(
        String(value, "artifact_id"), String(value, "content_hash"), String(value, "media_type"),
        String(value, "uri"), String(value, "sensitivity"), String(value, "acl_fingerprint"));

    private static NativeJsonObject Payload(NativeEnvelope envelope) => ProviderOfficeEventLog.Payload(envelope);
    private static NativeJsonObject Object(NativeJsonObject value, string key) => ProviderOfficeEventLog.Object(value, key);
    private static string String(NativeJsonObject value, string key) => ProviderOfficeEventLog.String(value, key);
    private static long Integer(NativeJsonObject value, string key) => ProviderOfficeEventLog.Integer(value, key);
    private static bool Boolean(NativeJsonObject value, string key) => ProviderOfficeEventLog.Boolean(value, key);
    private static long Cursor(NativeEnvelope envelope) => ProviderOfficeEventLog.Cursor(envelope);
}
