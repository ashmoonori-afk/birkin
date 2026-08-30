using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Tests.Support;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Transport;

[TestClass]
[TestCategory("LiveBridge")]
[TestCategory("WindowsOnly")]
[TestCategory("OfficeWorkflow")]
public sealed class OfficeAuthorityBridgeIntegrationTests
{
    [TestMethod]
    public async Task ProductionSession_ImportsComparesAndCreatesApprovedOfficeDraft()
    {
        var launcher = RealBridgeHarness.CreateStartInfo("test-home", "test-bridge");
        var expectedPython = OperatingSystem.IsWindows()
            ? Path.Combine(".venv", "Scripts", "python.exe")
            : Path.Combine(".venv", "bin", "python");
        StringAssert.EndsWith(launcher.FileName, expectedPython);
        CollectionAssert.AreEqual(
            new[]
            {
                "-m", "birkin.native.serve",
                "--transport", "loopback", "--root", "test-bridge",
            },
            launcher.ArgumentList.ToArray());
        var stderrFailure = Assert.ThrowsException<InvalidOperationException>(() =>
            RealBridgeHarness.ValidateStandardError("E_BRIDGE_SENTINEL unexpected bridge failure"));
        StringAssert.Contains(stderrFailure.Message, "E_BRIDGE_SENTINEL");

        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var started = await RealBridgeHarness.StartAsync(deadline.Token);
        await using var bridge = started.Harness;
        var store = new NativeProjectionStore();
        await using var session = new BridgeSession(store);
        await session.ConnectAsync(started.Announcement, started.Announcement.ServerVersion, deadline.Token);
        var fixtureRoot = Path.Combine(
            RealBridgeHarness.RepositoryRoot,
            "windows", "BirkinNativeApp", "tests", "Birkin.Native.App.Tests", "Fixtures", "Office");

        var imported = new Dictionary<string, NativeJsonObject>(StringComparer.Ordinal);
        foreach (var name in new[] { "baseline.xlsx", "candidate.xlsx", "report-template.docx" })
        {
            var commandId = $"w5-import-{Path.GetFileNameWithoutExtension(name)}";
            var receipt = await SendAndAwaitEventsAsync(
                session,
                store,
                ImportCommands.Import(
                    new FileImportIntent(Path.Combine(fixtureRoot, name)),
                    Context(commandId, store)),
                ["office.updated", "command.completed"],
                deadline.Token);
            imported[name] = Object(Object(receipt.Body, "result"), "artifact");
        }

        var compareReceipt = await SendAndAwaitEventsAsync(
            session,
            store,
            OfficeCommands.Compare(
                new OfficeCompareIntent(
                    String(imported["baseline.xlsx"], "artifact_id"),
                    String(imported["candidate.xlsx"], "artifact_id")),
                Context("w5-compare", store)),
            ["office.diff_ready", "command.completed"],
            deadline.Token);
        var diff = Object(Object(compareReceipt.Body, "result"), "diff");
        var diffId = String(diff, "diff_id");
        var identity = $"{{\"left\":\"{String(imported["baseline.xlsx"], "content_hash")}\",\"right\":\"{String(imported["candidate.xlsx"], "content_hash")}\",\"version\":{Integer(diff, "version")}}}";
        var expectedDiffId = $"diff-{Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity))).ToLowerInvariant()[..32]}";
        Assert.AreEqual(expectedDiffId, diffId);
        var serializedDiff = Encoding.UTF8.GetString(NativeJsonSerializer.Serialize(diff));
        StringAssert.Contains(serializedDiff, "4100");
        StringAssert.Contains(serializedDiff, "4700");

        const string outputName = "comparison-report.docx";
        var output = Path.Combine(bridge.BridgeRoot, outputName);
        var draftEvents = new List<NativeEnvelope>();
        var draftReceipt = await SendAndAwaitEventsAsync(
            session,
            store,
            OfficeCommands.Draft(
                new OfficeDraftIntent(
                    "Create the comparison report",
                    "docx",
                    new OfficeDocumentContent([
                        "BIRKIN_P3_03_DOCUMENT_SENTINEL",
                        "Comparison!A1 changed from 4100 to 4700.",
                    ]),
                    "Create a new comparison report",
                    outputName,
                    false),
                Context("w5-draft", store)),
            ["approval.requested", "command.completed"],
            deadline.Token,
            draftEvents);
        var draftResult = Object(draftReceipt.Body, "result");
        var approval = Object(draftResult, "approval");
        var approvalId = String(draftResult, "id");
        var jobId = String(approval, "job_id");
        Assert.AreEqual("office_create", String(draftResult, "category"));
        Assert.IsFalse(File.Exists(output), "Python must not write the draft before approval");
        var requested = draftEvents.Single(EventTypeIs("approval.requested"));
        Assert.AreEqual(approvalId, String(Object(requested.Body, "payload"), "approval_id"));
        Assert.AreEqual(jobId, String(Object(requested.Body, "payload"), "job_id"));
        Assert.IsTrue(Boolean(Object(requested.Body, "payload"), "sealed"));

        var approvalEvents = new List<NativeEnvelope>();
        var approvalReceipt = await SendAndAwaitEventsAsync(
            session,
            store,
            ApprovalCommands.Answer(
                new ApprovalAnswerIntent(approvalId, ApprovalDecision.Approve),
                Context("w5-approve", store)),
            ["approval.answered", "command.completed"],
            deadline.Token,
            approvalEvents);
        var approvalResult = Object(approvalReceipt.Body, "result");
        Assert.AreEqual("approved", String(approvalResult, "outcome"));
        StringAssert.Contains(String(approvalResult, "receipt"), jobId);
        Assert.IsTrue(File.Exists(output));

        using (var package = ZipFile.OpenRead(output))
        {
            var xml = string.Join("\n", package.Entries
                .Where(entry => entry.FullName.EndsWith(".xml", StringComparison.Ordinal))
                .Select(ReadEntry));
            StringAssert.Contains(xml, "BIRKIN_P3_03_DOCUMENT_SENTINEL");
            StringAssert.Contains(xml, "4100");
            StringAssert.Contains(xml, "4700");
        }

        var office = store.Surface("office") ?? throw new AssertFailedException("Office surface was not projected");
        var documents = Array(office.Payload, "documents").Values.Cast<NativeJsonObject>().ToArray();
        Assert.IsTrue(imported.Values.All(artifact =>
            documents.Any(item => String(item, "artifact_id") == String(artifact, "artifact_id"))));
        Assert.AreEqual(1, session.MaximumConcurrentReceives);
    }

    private static async Task<NativeEnvelope> SendAndAwaitEventsAsync(
        BridgeSession session,
        NativeProjectionStore store,
        NativeCommandRequest request,
        IReadOnlyCollection<string> expectedTypes,
        CancellationToken cancellationToken,
        List<NativeEnvelope>? captured = null)
    {
        var remaining = new HashSet<string>(expectedTypes, StringComparer.Ordinal);
        var eventsApplied = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void Applied(NativeEnvelope envelope)
        {
            if (envelope.Kind != NativeMessageKind.Event
                || envelope.Body["command_id"] is not NativeJsonString commandId
                || !string.Equals(commandId.Value, request.CommandId, StringComparison.Ordinal)
                || envelope.Body["type"] is not NativeJsonString type)
            {
                return;
            }
            captured?.Add(envelope);
            if (string.Equals(type.Value, "command.failed", StringComparison.Ordinal))
            {
                eventsApplied.TrySetException(new AssertFailedException(
                    $"Command {request.CommandId} failed: "
                    + Encoding.UTF8.GetString(
                        NativeJsonSerializer.Serialize(envelope.ToJsonValue()))));
                return;
            }
            _ = remaining.Remove(type.Value);
            if (remaining.Count == 0)
            {
                eventsApplied.TrySetResult();
            }
        }

        store.CanonicalApplied += Applied;
        try
        {
            var receiptTask = session.SendCommandForResultAsync(request, cancellationToken).AsTask();
            await eventsApplied.Task.WaitAsync(cancellationToken);
            return await receiptTask.WaitAsync(cancellationToken);
        }
        finally
        {
            store.CanonicalApplied -= Applied;
        }
    }

    private static CommandRequestContext Context(string commandId, NativeProjectionStore store) =>
        new(commandId, store.State?.Cursor ?? 0, NativeHandshake.ViewId);

    private static Func<NativeEnvelope, bool> EventTypeIs(string expected) => envelope =>
        envelope.Body["type"] is NativeJsonString type
        && string.Equals(type.Value, expected, StringComparison.Ordinal);

    private static string ReadEntry(ZipArchiveEntry entry)
    {
        using var reader = new StreamReader(entry.Open(), Encoding.UTF8);
        return reader.ReadToEnd();
    }

    private static NativeJsonObject Object(NativeJsonObject value, string key) =>
        value[key] as NativeJsonObject ?? throw new AssertFailedException($"{key} is not an object");

    private static NativeJsonArray Array(NativeJsonObject value, string key) =>
        value[key] as NativeJsonArray ?? throw new AssertFailedException($"{key} is not an array");

    private static string String(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text
            ? text.Value
            : throw new AssertFailedException($"{key} is not a string");

    private static long Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer
            ? integer.Value
            : throw new AssertFailedException($"{key} is not an integer");

    private static bool Boolean(NativeJsonObject value, string key) =>
        value[key] is NativeJsonBoolean flag
            ? flag.Value
            : throw new AssertFailedException($"{key} is not a boolean");
}
