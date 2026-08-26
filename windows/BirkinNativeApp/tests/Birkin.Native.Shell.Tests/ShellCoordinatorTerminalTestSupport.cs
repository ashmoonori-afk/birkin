using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

internal static class ShellCoordinatorTerminalTestSupport
{
    internal const string InstanceId = "abcdef0123456789abcdef0123456789";

    internal static async Task<bool> InvokeAsync(
        ShellCoordinator coordinator,
        string methodName,
        params object?[] arguments)
    {
        var argumentTypes = arguments.Select(argument => argument?.GetType() ?? typeof(object)).ToArray();
        var method = typeof(ShellCoordinator).GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .SingleOrDefault(candidate =>
            {
                if (candidate.Name != methodName || candidate.GetParameters().Length != arguments.Length)
                {
                    return false;
                }
                return candidate.GetParameters().Zip(argumentTypes)
                    .All(pair => pair.First.ParameterType.IsAssignableFrom(pair.Second));
            });
        Assert.IsNotNull(method, $"ShellCoordinator must provide {methodName} with typed arguments");
        try
        {
            var result = method.Invoke(coordinator, arguments);
            Assert.IsInstanceOfType<Task<bool>>(result);
            return await (Task<bool>)result;
        }
        catch (TargetInvocationException error) when (error.InnerException is not null)
        {
            ExceptionDispatchInfo.Capture(error.InnerException).Throw();
            throw;
        }
    }

    internal static void AssertAvailability(
        ShellPresentationModel model,
        string propertyName,
        bool enabled,
        string? reason)
    {
        var availability = Property(TerminalWorkflow(model), propertyName);
        Assert.IsNotNull(availability, $"terminal workflow must expose {propertyName}");
        Assert.AreEqual(enabled, Property(availability, "IsEnabled"));
        Assert.AreEqual(reason, Property(availability, "DisabledReason"));
    }

    internal static void AssertState(ShellPresentationModel model, string expected) =>
        Assert.AreEqual(expected, Property(TerminalWorkflow(model), "CommandState")?.ToString());

    internal static object TerminalWorkflow(ShellPresentationModel model) =>
        Property(model, "TerminalWorkflow")
        ?? throw new AssertFailedException("ShellPresentationModel must expose terminal workflow state");

    internal static void AssertNoPublicLease(ShellPresentationModel model)
    {
        var workflow = TerminalWorkflow(model);
        Assert.IsFalse(workflow.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .Any(property => property.Name.Contains("Lease", StringComparison.OrdinalIgnoreCase)));
        if (model.Workspace is { } workspace)
        {
            Assert.IsFalse(workspace.Terminal.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public)
                .Any(property => property.Name.Contains("Lease", StringComparison.OrdinalIgnoreCase)));
        }
    }

    internal static object? Property(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public)?.GetValue(target);

    internal static string? StringProperty(object target, string name) => Property(target, name) as string;

    internal static long? LongProperty(object target, string name) => Property(target, name) switch
    {
        long value => value,
        null => null,
        _ => throw new AssertFailedException($"{name} must be a long"),
    };

    internal static void AssertPayload(
        NativeCommandRequest request,
        string commandType,
        NativeJsonObject payload)
    {
        Assert.AreEqual(commandType, request.CommandType);
        CollectionAssert.AreEqual(
            NativeJsonSerializer.Serialize(payload),
            NativeJsonSerializer.Serialize(request.Payload));
    }

    internal static NativeEnvelope Receipt(
        string commandId,
        long cursor,
        NativeJsonObject result) => new(
        NativeMessageKind.Receipt,
        $"receipt-{commandId}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("command_id", new NativeJsonString(commandId)),
            ("session_id", new NativeJsonString("session-1")),
            ("actor_id", new NativeJsonString("windows:terminal")),
            ("accepted_cursor", new NativeJsonInteger(cursor)),
            ("state", new NativeJsonString("completed")),
            ("result_event_cursor", new NativeJsonInteger(cursor)),
            ("duplicate", new NativeJsonBoolean(false)),
            ("outcome", new NativeJsonString("accepted")),
            ("result", result)));

    internal static NativeCommandRefusal Refusal(
        string code,
        string commandId,
        long? cursor,
        string? approvalId,
        string message) =>
        (NativeCommandRefusal)(Activator.CreateInstance(
            typeof(NativeCommandRefusal),
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            args: [code, message, commandId, cursor, approvalId],
            culture: null) ?? throw new AssertFailedException());

    internal static NativeEnvelope Snapshot(long cursor, params NativeJsonObject[] terminals) => new(
        NativeMessageKind.Snapshot,
        $"snapshot-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("panels", new NativeJsonArray([])),
            ("conversation", new NativeJsonArray([])),
            ("composer", Object(("can_send", new NativeJsonBoolean(true)))),
            ("status", Object(("connection", new NativeJsonString("connected")))),
            ("working_memory", Object()),
            ("approval_policy", Object()),
            ("terminals", new NativeJsonArray(terminals)),
            ("instance_id", new NativeJsonString(InstanceId)),
            ("reset_reason", new NativeJsonString("initial"))));

    internal static NativeJsonObject Terminal(
        string terminalId,
        string display,
        string state,
        bool readOnly) => Object(
        ("terminal_id", new NativeJsonString(terminalId)),
        ("cwd", new NativeJsonString(@"C:\workspace\terminal-73")),
        ("screen", new NativeJsonString(display)),
        ("display", new NativeJsonString(display)),
        ("output_sequence", new NativeJsonInteger(19)),
        ("state", new NativeJsonString(state)),
        ("exit_status", NativeJsonNull.Value),
        ("columns", new NativeJsonInteger(137)),
        ("rows", new NativeJsonInteger(43)),
        ("read_only", new NativeJsonBoolean(readOnly)));

    internal static NativeEnvelope TerminalEvent(
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
            ("timestamp", new NativeJsonString("2037-04-05T06:07:08Z")),
            ("actor_id", new NativeJsonString("native-human-73")),
            ("command_id", new NativeJsonString(commandId)),
            ("payload", payload)));

    internal static string String(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text
            ? text.Value
            : throw new AssertFailedException($"{key} must be a string");

    internal static long Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer
            ? integer.Value
            : throw new AssertFailedException($"{key} must be an integer");

    internal static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    internal static IReadOnlySet<string> Commands(params string[] values) =>
        new HashSet<string>(values, StringComparer.Ordinal);
    internal sealed class TestConnection(
        NativeProjectionStore store,
        IReadOnlySet<string> advertisedCommands) : INativeClientConnection
    {
        private readonly Queue<object> _results = new();

        public bool IsCapabilityLive { get; set; } = true;
        public IReadOnlySet<string> AdvertisedCommands { get; set; } = advertisedCommands;
        public Action<NativeCommandRequest>? BeforeResult { get; set; }
        public bool OwnsReceiveLoop => true;
        public NativeProjectionStore ProjectionStore { get; } = store;
        public List<NativeCommandRequest> Sent { get; } = [];

        public bool HasLiveCapability(DateTimeOffset now) => IsCapabilityLive;
        public void Enqueue(NativeEnvelope receipt) => _results.Enqueue(receipt);
        public void Enqueue(NativeCommandRefusal refusal) => _results.Enqueue(refusal);
        public Task ConnectAsync(BridgeAnnouncement announcement, string expectedProductVersion,
            CancellationToken cancellationToken) => Task.CompletedTask;
        public ValueTask<NativeEnvelope> SendCommandForResultAsync(
            NativeCommandRequest request,
            CancellationToken cancellationToken)
        {
            Sent.Add(request);
            BeforeResult?.Invoke(request);
            return _results.Dequeue() switch
            {
                NativeEnvelope receipt => ValueTask.FromResult(receipt),
                NativeCommandRefusal refusal => ValueTask.FromException<NativeEnvelope>(refusal),
                _ => throw new AssertFailedException(),
            };
        }
        public ValueTask<NativeEnvelope> ReceiveAsync(CancellationToken cancellationToken) =>
            ValueTask.FromException<NativeEnvelope>(new NotSupportedException());
        public ValueTask DisposeAsync()
        {
            IsCapabilityLive = false;
            _results.Clear();
            return ValueTask.CompletedTask;
        }
    }
}
