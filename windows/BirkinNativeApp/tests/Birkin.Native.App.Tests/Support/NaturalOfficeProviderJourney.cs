using System.IO;
using System.IO.Compression;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class NaturalOfficeProviderJourney
{
    private const string OutputName = "natural-office-approved.docx";
    private const string ExpectedTitle = "Birkin Natural Office Gate";
    private const string ExpectedParagraph = "자연어 요청으로 안전하게 수정되었습니다.";

    public static async Task RunAsync()
    {
        var repositoryRoot = FindRepositoryRoot();
        var configuredEvidenceRoot = Environment.GetEnvironmentVariable("BIRKIN_NATIVE_EVIDENCE_ROOT");
        Assert.IsFalse(string.IsNullOrWhiteSpace(configuredEvidenceRoot),
            "BIRKIN_NATIVE_EVIDENCE_ROOT is required for the actual natural-language gate");
        var evidenceRoot = Path.Combine(configuredEvidenceRoot!, "natural-office");
        var evidence = new ProviderOfficeEvidence(evidenceRoot);
        using var setupDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var bridge = await BridgeProcessHarness.StartAsync(setupDeadline.Token);
        Exception? journeyFailure = null;
        try
        {
            await using (bridge)
            {
                var announcementJson = await bridge.WaitForListeningAsync(setupDeadline.Token);
                var announcementFile = Path.Combine(bridge.TemporaryRoot, "announcement.jsonl");
                await File.WriteAllTextAsync(announcementFile, announcementJson + Environment.NewLine, setupDeadline.Token);
                var options = AppOptions.Parse(["--bridge-announcement-file", announcementFile]);
                await using var sta = await StaDispatcherHarness.StartAsync(CancellationToken.None);
                var journey = sta.InvokeAsync(async () =>
                {
                    using var sessionLifetime = new CancellationTokenSource();
                    await using var composition = CompositionRoot.Create(
                        SynchronizationContext.Current
                        ?? throw new InvalidOperationException("WPF dispatcher synchronization context is unavailable"));
                    var initial = new TaskCompletionSource<WorkspaceSnapshotPresentation>(TaskCreationOptions.RunContinuationsAsynchronously);
                    composition.Coordinator.SnapshotApplied += InitialApplied;
                    try
                    {
                        await composition.Runner.RunAsync(options, sessionLifetime.Token);
                        _ = await initial.Task.WaitAsync(setupDeadline.Token);
                        Assert.AreEqual(ConnectionState.Ready, composition.PresentationModel.Connection.State);
                        Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("chat.send"));
                        Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("file.import"));
                        Assert.IsTrue(composition.Session.AdvertisedCommands.Contains("approval.answer"));
                        using var gateDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(240));
                        await RunGateAsync(repositoryRoot, bridge.TemporaryRoot, composition, evidence, evidenceRoot, gateDeadline.Token);
                    }
                    finally
                    {
                        composition.Coordinator.SnapshotApplied -= InitialApplied;
                        sessionLifetime.Cancel();
                    }

                    void InitialApplied(WorkspaceSnapshotPresentation snapshot) => initial.TrySetResult(snapshot);
                });
                try
                {
                    await journey;
                    evidence.CaptureWorkspace(bridge.TemporaryRoot);
                }
                catch (Exception error)
                {
                    journeyFailure ??= error;
                    evidence.Record("failure-diagnostics", new Dictionary<string, object?>
                    {
                        ["stderr_bytes"] = Encoding.UTF8.GetByteCount(bridge.StandardError),
                        ["stderr_sha256"] = ProviderOfficeEvidence.Hash(bridge.StandardError),
                    });
                    evidence.CaptureWorkspace(bridge.TemporaryRoot);
                    throw;
                }
            }
        }
        catch (Exception error)
        {
            journeyFailure ??= error;
        }
        finally
        {
            Exception? cleanupFailure = null;
            try
            {
                evidence.Record("cleanup", new Dictionary<string, object?>
                {
                    ["owned_process_exited"] = bridge.OwnedProcessExited,
                    ["temporary_root_deleted"] = bridge.TemporaryRootDeleted,
                });
                Assert.IsTrue(bridge.OwnedProcessExited, "the exact owned bridge Process did not exit");
                Assert.IsTrue(bridge.TemporaryRootDeleted, "the exact owned temporary root was not deleted");
            }
            catch (Exception error)
            {
                cleanupFailure = error;
            }
            if (cleanupFailure is not null)
            {
                if (journeyFailure is null)
                {
                    ExceptionDispatchInfo.Capture(cleanupFailure).Throw();
                }
                journeyFailure.Data["cleanup_failure"] = cleanupFailure.Message;
            }
        }
        if (journeyFailure is not null)
        {
            ExceptionDispatchInfo.Capture(journeyFailure).Throw();
        }
    }

    private static async Task RunGateAsync(
        string repositoryRoot,
        string temporaryRoot,
        CompositionRoot composition,
        ProviderOfficeEvidence evidence,
        string evidenceRoot,
        CancellationToken cancellationToken)
    {
        var window = new MainWindow(composition.PresentationModel, composition.Coordinator)
        {
            Width = 1500,
            Height = 940,
            WindowStartupLocation = WindowStartupLocation.Manual,
        };
        window.Show();
        window.Activate();
        window.UpdateLayout();
        var approvals = OfficeWorkflowViewHarness.Find<ApprovalView>(window, "approval.workflow");
        approvals.ConfirmDecision = (_, _) => true;
        using var events = new ProviderOfficeEventLog(composition.ProjectionStore);
        try
        {
            var fixture = Path.Combine(repositoryRoot,
                "windows", "BirkinNativeApp", "tests", "Birkin.Native.App.Tests", "Fixtures", "Office", "report-template.docx");
            var importPanel = OfficeWorkflowViewHarness.Find<Expander>(window, "office.import-panel");
            importPanel.IsExpanded = true;
            await RenderBarrierAsync(window);
            OfficeWorkflowViewHarness.Find<TextBox>(window, "import.path").Text = fixture;
            var importTrace = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events,
                OfficeWorkflowViewHarness.Find<Button>(window, "import.submit"),
                "file.import", cancellationToken);
            _ = await events.WaitAsync("office.updated", importTrace.CommandId, cancellationToken);
            await RenderBarrierAsync(window);
            var imported = composition.PresentationModel.OfficeWorkflow.Imports.Single(item => item.DisplayName == "report-template.docx");
            var attachment = OfficeWorkflowViewHarness.Find<CheckBox>(window, imported.ImportId);
            attachment.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.IsTrue(composition.PresentationModel.OfficeWorkflow.Imports.Single(item => item.ImportId == imported.ImportId).IsSelected);

            var outputPath = Path.Combine(temporaryRoot, "workspace", OutputName);
            Assert.IsFalse(File.Exists(outputPath));
            var request = $"""
                birkin MCP 도구가 바로 보이지 않으면 tool_search_tool로 inspect_document와 office_job_request를 먼저 찾으세요. 첨부한 report-template.docx를 inspect_document로 검사한 뒤, 첫 번째 문단은 '{ExpectedTitle}', 두 번째 문단은 '{ExpectedParagraph}'로 바꾸는 office_job_request 승인 요청을 만들고 각 입력은 해당 도구 schema를 따르세요. 결과 저장 위치는 정확히 '{outputPath}'입니다. 파일을 직접 만들거나 셸을 사용하지 말고, 두 도구 호출 뒤 승인 요청을 접수했다는 짧은 확인만 답하세요.
                """;
            OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft").Text = request;
            var chat = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events,
                OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send"),
                "chat.send", cancellationToken);
            var assistantText = ProviderOfficeEventLog.String(ProviderOfficeEventLog.Payload(
                events.Events.Single(item => ProviderOfficeEventLog.CommandId(item) == chat.CommandId
                    && ProviderOfficeEventLog.Type(item) == "message.assistant.completed")), "text");
            var assistantBytes = Encoding.UTF8.GetBytes(assistantText);
            var boundedAssistant = Encoding.UTF8.GetString(assistantBytes, 0, Math.Min(assistantBytes.Length, 16_000));
            File.WriteAllText(Path.Combine(evidenceRoot, "diagnostic-assistant.txt"),
                $"truncated={assistantBytes.Length > 16_000}\n{boundedAssistant}", Encoding.UTF8);
            var inspectStarts = events.Events.Where(item =>
                ProviderOfficeEventLog.CommandId(item) == chat.CommandId
                && ProviderOfficeEventLog.Type(item) == "tool.started"
                && RuntimeName(item) == "inspect_document").ToArray();
            var inspectEnds = events.Events.Where(item =>
                ProviderOfficeEventLog.CommandId(item) == chat.CommandId
                && ProviderOfficeEventLog.Type(item) == "tool.completed"
                && RuntimeName(item) == "inspect_document").ToArray();
            var inspectFailures = events.Events.Count(item =>
                ProviderOfficeEventLog.CommandId(item) == chat.CommandId
                && ProviderOfficeEventLog.Type(item) == "tool.failed"
                && RuntimeName(item) == "inspect_document");
            Assert.AreEqual(1, inspectEnds.Length,
                $"inspection did not complete exactly once; started={inspectStarts.Length}; completed={inspectEnds.Length}; failed={inspectFailures}");
            var inspectEnd = inspectEnds[0];
            var inspectStart = inspectStarts.Single(item => RuntimeItemId(item) == RuntimeItemId(inspectEnd));
            var requestEnd = events.Events.Single(item =>
                ProviderOfficeEventLog.CommandId(item) == chat.CommandId
                && ProviderOfficeEventLog.Type(item) == "tool.completed"
                && RuntimeName(item) == "office_job_request");
            Assert.IsTrue(ProviderOfficeEventLog.Cursor(inspectStart) < ProviderOfficeEventLog.Cursor(inspectEnd));
            Assert.IsTrue(ProviderOfficeEventLog.Cursor(inspectEnd) < ProviderOfficeEventLog.Cursor(requestEnd));
            var approval = composition.PresentationModel.Workspace!.ApprovalRequests.Single(item =>
                item.Category == "office_job" && item.Destination == outputPath && !item.Decided);
            Assert.IsNotNull(approval.Id);
            Assert.IsFalse(File.Exists(outputPath), "provider tool request produced output before Native approval");
            evidence.Record("natural-tool-lineage", new Dictionary<string, object?>
            {
                ["chat_command_id"] = chat.CommandId,
                ["inspect_started_cursor"] = ProviderOfficeEventLog.Cursor(inspectStart),
                ["inspect_completed_cursor"] = ProviderOfficeEventLog.Cursor(inspectEnd),
                ["job_request_completed_cursor"] = ProviderOfficeEventLog.Cursor(requestEnd),
                ["approval_id"] = approval.Id,
                ["destination_sha256"] = ProviderOfficeEvidence.Hash(outputPath),
            });
            await RenderBarrierAsync(window);
            var before = ProviderOfficeScreenshot.CaptureRedacted(
                window, Path.Combine(evidenceRoot, "natural-office-pre-approval-1500x940.png"), 1500, 940);
            evidence.Record("pre-approval-screenshot", new Dictionary<string, object?>
            {
                ["approval_id"] = approval.Id,
                ["png_sha256"] = before.Sha256,
            });
            var approve = OfficeWorkflowViewHarness.Find<Button>(window, $"approval.approve.{approval.Id}");
            Assert.IsTrue(approve.IsEnabled);
            var answer = await ProviderOfficeJourneyActions.ClickAsync(
                composition.PresentationModel, events, approve, "approval.answer", cancellationToken);
            var answered = await events.WaitAsync("approval.answered", answer.CommandId, cancellationToken);
            Assert.AreEqual(approval.Id, ProviderOfficeEventLog.String(ProviderOfficeEventLog.Payload(answered), "approval_id"));
            Assert.IsTrue(File.Exists(outputPath));
            AssertDocument(outputPath);
            File.Copy(outputPath, Path.Combine(evidenceRoot, OutputName), overwrite: false);
            await RenderBarrierAsync(window);
            var after = ProviderOfficeScreenshot.CaptureRedacted(
                window, Path.Combine(evidenceRoot, "natural-office-post-save-1500x940.png"), 1500, 940);
            evidence.Record("post-save-screenshot", new Dictionary<string, object?>
            {
                ["approval_id"] = approval.Id,
                ["answered_cursor"] = ProviderOfficeEventLog.Cursor(answered),
                ["png_sha256"] = after.Sha256,
                ["output_sha256"] = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(outputPath))).ToLowerInvariant(),
            });
            var receipt = await events.WaitAsync("receipt.recorded", answer.CommandId, cancellationToken);
            var receiptPayload = ProviderOfficeEventLog.Payload(receipt);
            Assert.AreEqual(approval.Id, ProviderOfficeEventLog.String(receiptPayload, "approval_id"));
            Assert.AreEqual("등록된 구조 검증 통과", ProviderOfficeEventLog.String(receiptPayload, "validation_summary"));
        }
        finally
        {
            window.Close();
        }
    }

    private static string RuntimeName(Birkin.Native.Protocol.Framing.NativeEnvelope envelope) =>
        ProviderOfficeEventLog.String(ProviderOfficeEventLog.Payload(envelope), "runtime_name");

    private static string RuntimeItemId(Birkin.Native.Protocol.Framing.NativeEnvelope envelope) =>
        ProviderOfficeEventLog.String(ProviderOfficeEventLog.Payload(envelope), "runtime_item_id");

    private static void AssertDocument(string path)
    {
        using var archive = ZipFile.OpenRead(path);
        var document = archive.GetEntry("word/document.xml")
            ?? throw new AssertFailedException("DOCX main document part is missing");
        using var reader = new StreamReader(document.Open());
        var xml = reader.ReadToEnd();
        StringAssert.Contains(xml, ExpectedTitle);
        StringAssert.Contains(xml, ExpectedParagraph);
    }

    private static async Task RenderBarrierAsync(Window window)
    {
        await window.Dispatcher.InvokeAsync(window.UpdateLayout);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        window.UpdateLayout();
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
        {
            directory = directory.Parent;
        }
        return directory?.FullName ?? throw new InvalidOperationException("repository root was not found");
    }
}
