using System.IO;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Views;
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
        var approvals = OfficeWorkflowViewHarness.Find<ApprovalView>(
            window,
            "approval.workflow");
        approvals.ConfirmDecision = (_, _) => true;
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
            await RenderBarrierAsync(window);
            var diffView = OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "diff.landmark");
            var diffItems = OfficeWorkflowViewHarness.Find<ItemsControl>(window, "diff.items");
            Assert.AreEqual(Visibility.Visible, diffView.Visibility);
            var canonicalChange = diffItems.Items.Cast<Birkin.Native.Shell.Presentation.OfficeDiffRowPresentation>()
                .First(row => row.OldValue.Contains("4100", StringComparison.Ordinal)
                    && row.NewValue.Contains("4700", StringComparison.Ordinal));
            Assert.IsFalse(string.IsNullOrWhiteSpace(canonicalChange.Label));

            if (!composition.PresentationModel.OfficeWorkflow.Availability.OfficeDraft.IsEnabled)
            {
                var comparisonPath = Path.Combine(evidenceRoot, "read-only-office-diff-1500x940.png");
                var comparison = ProviderOfficeScreenshot.CaptureRedacted(window, comparisonPath, 1500, 940);
                evidence.Record("read-only-office-diff", new Dictionary<string, object?>
                {
                    ["diff_id"] = diffId,
                    ["png_sha256"] = comparison.Sha256,
                    ["width"] = comparison.Width,
                    ["height"] = comparison.Height,
                    ["save_disabled_reason"] = composition.PresentationModel.OfficeWorkflow.Availability.OfficeDraft.DisabledReason,
                });
                var readOnlyProviderInvocations = events.Events.Count(envelope =>
                    ProviderOfficeEventLog.Type(envelope) == "message.user");
                Assert.AreEqual(invokeProvider ? 1 : 0, readOnlyProviderInvocations);
                return new ProviderOfficeFlowResult(readOnlyProviderInvocations);
            }

            const string outputName = "comparison-report.docx";
            var outputPath = Path.Combine(
                temporaryRoot, "workspace", outputName);
            var draft = await ProviderOfficeJourneyActions.SubmitAsync(
                composition.PresentationModel,
                events,
                "office.job_request",
                () => composition.Coordinator.DraftOfficeDocumentAsync(
                    new OfficeDraftIntent(
                        "Create the provider comparison report",
                        "docx",
                        new OfficeDocumentContent([
                            "BIRKIN_P3_03_DOCUMENT_SENTINEL",
                            "Comparison!A1 changed from 4100 to 4700.",
                        ]),
                        "Create a new provider comparison report",
                        outputPath,
                        false),
                    cancellationToken),
                cancellationToken);
            var requested = await events.WaitAsync("approval.requested", draft.CommandId, cancellationToken);
            var requestedPayload = Payload(requested);
            var approvalId = String(requestedPayload, "approval_id");
            var jobId = String(requestedPayload, "job_id");
            Assert.AreEqual("office_create", String(requestedPayload, "category"));
            Assert.IsTrue(Boolean(requestedPayload, "sealed"));
            Assert.IsFalse(File.Exists(outputPath), "output existed before visible approval");

            await RenderBarrierAsync(window);
            var scroll = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "context.scroll");
            diffView.BringIntoView();
            await RenderBarrierAsync(window);
            var oldValue = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "diff.old-value")
                .First(text => text.Text.Contains("4100", StringComparison.Ordinal));
            var newValue = OfficeWorkflowViewHarness.FindAll<TextBlock>(window, "diff.new-value")
                .First(text => text.Text.Contains("4700", StringComparison.Ordinal));
            Assert.IsTrue(IsInViewport(diffView, scroll), "the Python diff was not visibly in the pre-approval viewport");
            Assert.IsTrue(IsInViewport(oldValue, scroll) && IsInViewport(newValue, scroll),
                "the labeled 4100 -> 4700 controls were not fully visible before approval");
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

            scroll.ScrollToHome();
            await RenderBarrierAsync(window);
            var approve = OfficeWorkflowViewHarness.Find<Button>(
                window,
                $"approval.approve.{approvalId}");
            Assert.AreEqual(approvalId, approve.Tag as string);
            Assert.IsTrue(approve.IsEnabled);
            approve.BringIntoView();
            await RenderBarrierAsync(window);
            Assert.IsTrue(IsInViewport(approve, scroll), "the exact projected approval was not visibly actionable");
            var approval = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events, approve, "approval.answer", cancellationToken);
            var answeredEvent = await events.WaitAsync(
                "approval.answered", approval.CommandId, cancellationToken);
            Assert.AreEqual("approve", String(Payload(answeredEvent), "decision"));
            Assert.IsTrue(File.Exists(outputPath), "approved DOCX was not exported");
            ProviderOfficePackageAssertions.AssertReport(outputPath);

            await RenderBarrierAsync(window);
            var receiptTraces = new ProviderOfficeCommandTrace?[] { chat, draft, approval }
                .OfType<ProviderOfficeCommandTrace>().ToArray();
            ProviderOfficeJourneyAssertions.AssertStoredReceipts(temporaryRoot, receiptTraces, evidence);
            scroll.ScrollToVerticalOffset(
                OfficeWorkflowViewHarness.Find<FrameworkElement>(window, "approvals.landmark").ActualHeight + 5);
            await RenderBarrierAsync(window);
            var afterPath = Path.Combine(evidenceRoot, "post-save-activity-office-1500x940.png");
            var after = ProviderOfficeScreenshot.CaptureRedacted(window, afterPath, 1500, 940);
            evidence.Record("post-save-screenshot", new Dictionary<string, object?>
            {
                ["approval_id"] = approvalId,
                ["job_id"] = jobId,
                ["answered_cursor"] = Cursor(answeredEvent),
                ["png_sha256"] = after.Sha256,
                ["width"] = after.Width,
                ["height"] = after.Height,
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
        var context = OfficeWorkflowViewHarness.Find<ScrollViewer>(window, "context.scroll");
        context.ScrollToEnd();
        await RenderBarrierAsync(window);
        var importPanel = OfficeWorkflowViewHarness.Find<Expander>(window, "office.import-panel");
        importPanel.BringIntoView();
        importPanel.IsExpanded = true;
        await RenderBarrierAsync(window);
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
        return artifacts;
    }

    private static async Task RenderBarrierAsync(Window window)
    {
        await window.Dispatcher.InvokeAsync(window.UpdateLayout);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        window.UpdateLayout();
    }

    private static bool IsInViewport(FrameworkElement element, FrameworkElement viewport)
    {
        var bounds = element.TransformToAncestor(viewport).TransformBounds(
            new Rect(new Point(0, 0), element.RenderSize));
        var visible = new Rect(new Point(0, 0), viewport.RenderSize);
        return element.IsVisible
            && bounds.Left >= visible.Left - 1
            && bounds.Top >= visible.Top - 1
            && bounds.Right <= visible.Right + 1
            && bounds.Bottom <= visible.Bottom + 1;
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
