using System.Windows;
using System.Windows.Automation;
using System.Windows.Media;
using Birkin.Native.App;
using Birkin.Native.App.Views;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Tests.Support;

internal sealed class OfficeWorkflowViewHarness : IAsyncDisposable
{
    private const string InstanceId = "0123456789abcdef0123456789abcdef";
    private long _cursor = 12;

    private OfficeWorkflowViewHarness(
        RecordingConnection connection,
        ShellPresentationModel model,
        ShellCoordinator coordinator)
    {
        Connection = connection;
        Model = model;
        Coordinator = coordinator;
    }

    public RecordingConnection Connection { get; }
    public ShellPresentationModel Model { get; }
    public ShellCoordinator Coordinator { get; }

    public static async Task<OfficeWorkflowViewHarness> CreateAsync(
        bool canInterrupt = false)
    {
        var connection = new RecordingConnection();
        connection.Enqueue(Snapshot(canInterrupt));
        var model = new ShellPresentationModel(new ImmediateSynchronizationContext());
        var coordinator = new ShellCoordinator(connection, new NativeProjectionStore(), model)
        {
            CommandIdFactory = () => $"command-{connection.Sent.Count + 1}",
        };
        await coordinator.ConnectAsync(
            $$"""{"event":"listening","transport":"loopback","pid":1,"root":"C:\\root","session_id":"session-1","instance_id":"{{InstanceId}}","server_version":"0.4.276","discovery_path":"C:\\root\\endpoint.json"}""",
            "0.4.276",
            CancellationToken.None);
        return new OfficeWorkflowViewHarness(connection, model, coordinator);
    }

    public async Task ResolveLastAsync()
    {
        var command = Connection.Sent[^1];
        _cursor++;
        Connection.Enqueue(Event(_cursor, command.CommandId));
        await Coordinator.ReceiveCanonicalAsync(CancellationToken.None);
    }

    public void ApplyCanonical(string type, NativeJsonObject payload)
    {
        _cursor++;
        Coordinator.ProjectionStore.ApplyEvent(Event(_cursor, "provider-office-test", type, payload));
    }

    public static T Find<T>(DependencyObject root, string automationId) where T : DependencyObject =>
        Descendants<T>(root).Single(element =>
            string.Equals(AutomationProperties.GetAutomationId(element), automationId, StringComparison.Ordinal));

    public static IReadOnlyList<T> FindAll<T>(DependencyObject root, string automationId) where T : DependencyObject =>
        Descendants<T>(root).Where(element =>
            string.Equals(AutomationProperties.GetAutomationId(element), automationId, StringComparison.Ordinal)).ToArray();

    public static WorkspaceSnapshotView Snapshot(MainWindow window) =>
        window.FindName("SnapshotView") as WorkspaceSnapshotView
        ?? throw new InvalidOperationException(
            "MainWindow did not create its WorkspaceSnapshotView.");

    public static void Layout(FrameworkElement view, double width = 1400, double height = 880)
    {
        view.Measure(new Size(width, height));
        view.Arrange(new Rect(0, 0, width, height));
        view.UpdateLayout();
    }

    public ValueTask DisposeAsync() => Coordinator.DisposeAsync();

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

    private static NativeEnvelope Snapshot(bool canInterrupt) => new(
        NativeMessageKind.Snapshot,
        "snapshot-1",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(12)),
            ("panels", new NativeJsonArray([
                Object(
                    ("key", new NativeJsonString("office")),
                    ("items", new NativeJsonArray([
                        Object(("id", new NativeJsonString("artifact-report")), ("kind", new NativeJsonString("document")), ("summary", new NativeJsonString("report-template.docx"))),
                        Object(("id", new NativeJsonString("diff-1")), ("kind", new NativeJsonString("diff")), ("summary", new NativeJsonString("BIRKIN_P3_03_SENTINEL: 4100 -> 4700")))
                    ]))),
                Object(
                    ("key", new NativeJsonString("approvals")),
                    ("items", new NativeJsonArray([
                        Object(
                            ("id", new NativeJsonString("approval-7")),
                            ("kind", new NativeJsonString("approval")),
                            ("summary", new NativeJsonString("Office 변경: 검토한 통합 문서 저장")),
                            ("description", new NativeJsonString("Comparison!A1 변경: 4100 → 4700")),
                            ("category", new NativeJsonString("office_job")),
                            ("risk", new NativeJsonString("high")),
                            ("sealed", new NativeJsonBoolean(true)),
                            ("decided", new NativeJsonBoolean(false)),
                            ("source_filename", new NativeJsonString("comparison-source.xlsx")),
                            ("destination", new NativeJsonString(@"C:\workspace\approved\comparison-report.xlsx")),
                            ("overwrite_approved", new NativeJsonBoolean(false)),
                            ("authority_digest", new NativeJsonString(new string('a', 64))),
                            ("requester", new NativeJsonString("native:office-journey")),
                            ("rejection_result", new NativeJsonString("거부하면 원본은 변경되지 않으며 새 파일도 저장되지 않습니다.")))
                    ]))),
                Object(("key", new NativeJsonString("activity_logs")), ("items", new NativeJsonArray([])))
            ])),
            ("conversation", new NativeJsonArray([
                Object(("id", new NativeJsonString("message-1")), ("kind", new NativeJsonString("user_message")), ("text", new NativeJsonString("기준 파일과 후보 파일을 비교해 주세요.")), ("actor_id", new NativeJsonString("user")), ("cursor", new NativeJsonInteger(10))),
                Object(("id", new NativeJsonString("approval-7")), ("kind", new NativeJsonString("approval")), ("text", new NativeJsonString("보고서 저장 승인 필요")), ("actor_id", new NativeJsonString("python:authority")), ("cursor", new NativeJsonInteger(12)))
            ])),
            ("composer", Object(
                ("can_send", new NativeJsonBoolean(true)),
                ("can_interrupt", new NativeJsonBoolean(canInterrupt)))),
            ("status", Object(("connection", new NativeJsonString("connected")))),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray([])),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    private static NativeEnvelope Receipt(
        NativeCommandRequest request,
        ImportedFilePresentation? imported) => new(
        NativeMessageKind.Receipt,
        $"receipt-{request.CommandId}",
        imported is null
            ? Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(request.CommandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:office")),
            ("accepted_cursor", new NativeJsonInteger(13)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(13)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted")))
            : Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(request.CommandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:office")),
            ("accepted_cursor", new NativeJsonInteger(13)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(13)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted")),
            ("result", Object(
                ("reference", Object(
                    ("kind", new NativeJsonString("workspace_import")),
                    ("import_id", new NativeJsonString(imported.ImportId)),
                    ("display_name", new NativeJsonString(imported.DisplayName)),
                    ("jail_name", new NativeJsonString(imported.JailName)),
                    ("sha256", new NativeJsonString(imported.Sha256)),
                    ("byte_count", new NativeJsonInteger(imported.ByteCount))))))));

    private static NativeEnvelope Event(long cursor, string commandId) =>
        Event(cursor, commandId, "command.completed", Object(("summary", new NativeJsonString("canonical completion"))));

    private static NativeEnvelope Event(
        long cursor,
        string commandId,
        string type,
        NativeJsonObject payload) => new(
        NativeMessageKind.Event,
        $"event-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("event_id", new NativeJsonString($"event-{cursor}")),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("type", new NativeJsonString(type)),
            ("timestamp", new NativeJsonString("2026-08-24T01:00:00+00:00")),
            ("actor_id", new NativeJsonString("python:authority")),
            ("command_id", new NativeJsonString(commandId)),
            ("payload", payload)));

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    internal sealed class RecordingConnection : INativeClientConnection
    {
        private readonly Queue<NativeEnvelope> _received = new();
        private readonly TaskCompletionSource<NativeCommandRequest> _firstCommandSent =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private static readonly HashSet<string> Commands =
        [
            "chat.send", "file.import", "approval.answer",
            "chat.interrupt",
            "office.select", "office.open", "office.compare",
            "office.job_request",
            "office.rollback_request",
        ];

        public List<NativeCommandRequest> Sent { get; } = [];
        public Task<NativeCommandRequest> FirstCommandSent =>
            _firstCommandSent.Task;
        public ImportedFilePresentation? NextImportReference { get; set; }
        public IReadOnlySet<string> AdvertisedCommands => Commands;
        public bool HasLiveCapability(DateTimeOffset now) => true;
        public void Enqueue(NativeEnvelope envelope) => _received.Enqueue(envelope);
        public Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion, CancellationToken cancellationToken) => Task.CompletedTask;
        public ValueTask SendCommandAsync(NativeCommandRequest request, CancellationToken cancellationToken)
        {
            Sent.Add(request);
            _firstCommandSent.TrySetResult(request);
            Enqueue(Receipt(request, NextImportReference));
            NextImportReference = null;
            return ValueTask.CompletedTask;
        }
        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken) =>
            ValueTask.FromResult(_received.Dequeue());
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
