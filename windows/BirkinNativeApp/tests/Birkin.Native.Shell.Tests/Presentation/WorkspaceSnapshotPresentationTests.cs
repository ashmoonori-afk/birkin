using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class WorkspaceSnapshotPresentationTests
{
    [TestMethod]
    public void FromProjection_WhenPythonGoldenSnapshotIsApplied_MapsCanonicalShellRegionsReadOnly()
    {
        // Given
        var path = Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(path));
        var vector = fixture.RootElement.GetProperty("snapshot");
        var frame = Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!);
        var store = new NativeProjectionStore();
        store.ApplySnapshot(
            NativeFrameCodec.Decode(frame),
            new NativeReadyIdentity("session-1", "instance-1", "fixture-version"));

        // When
        var presentation = WorkspaceSnapshotPresentation.FromProjection(store.State!, "loopback");

        // Then
        Assert.AreEqual("session-1", presentation.SessionId);
        Assert.AreEqual(10, presentation.PanelCount);
        Assert.AreEqual("connected", presentation.PythonConnection);
        Assert.AreEqual(2, presentation.Conversation.Count);
        Assert.AreEqual("user_message", presentation.Conversation[0].Kind);
        Assert.AreEqual("Ship the reducer", presentation.Conversation[0].Text);
        Assert.AreEqual("macos:window-main", presentation.Conversation[0].ActorId);
        Assert.AreEqual("assistant_message", presentation.Conversation[1].Kind);
        Assert.IsTrue(presentation.Composer.CanSend);
        Assert.IsFalse(presentation.Composer.IsEnabled);
        Assert.IsFalse(presentation.MutationAvailability.IsEnabled);
        CollectionAssert.AreEqual(
            new[] { "Goals", "Context", "Files", "Constraints", "Notes" },
            presentation.WorkingMemory.Rows.Select(row => row.Label).ToArray());
        CollectionAssert.AreEqual(
            new[] { "Ship native Working Memory" },
            presentation.WorkingMemory.Rows[0].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Use canonical state", "Delegate to Python", "RED captured" },
            presentation.WorkingMemory.Rows[1].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "workspace/main.py" },
            presentation.WorkingMemory.Rows[2].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Stay offline" },
            presentation.WorkingMemory.Rows[3].Values.ToArray());
        CollectionAssert.AreEqual(
            new[] { "Render five rows", "Run GREEN" },
            presentation.WorkingMemory.Rows[4].Values.ToArray());
        Assert.AreEqual(1L, presentation.WorkingMemory.Revision);
        Assert.AreEqual(3, presentation.Approvals.Count);
        Assert.IsTrue(presentation.Approvals.All(row => row.EffectiveState == "Ask"));
        Assert.IsTrue(presentation.Approvals.All(row => row.RequestedState == "Default"));
        Assert.AreEqual(0, presentation.Activity.Count);
        Assert.AreEqual(0, presentation.Browser.Count);
        Assert.AreEqual(0, presentation.Office.Count);
        Assert.IsFalse(presentation.Terminal.IsAvailable);
    }

    [TestMethod]
    public void FromProjection_WhenTerminalSnapshotExists_MapsAvailabilityDisplayAndReadOnlyState()
    {
        // Given
        var store = new NativeProjectionStore();
        store.ApplySnapshot(new NativeEnvelope(
            NativeMessageKind.Snapshot,
            "terminal-snapshot-73",
            Object(
                ("protocol_version", new NativeJsonInteger(1)),
                ("session_id", new NativeJsonString("terminal-session-29")),
                ("cursor", new NativeJsonInteger(61)),
                ("panels", new NativeJsonArray([])),
                ("conversation", new NativeJsonArray([])),
                ("composer", Object(("can_send", new NativeJsonBoolean(false)))),
                ("status", Object(("connection", new NativeJsonString("connected")))),
                ("working_memory", Object()),
                ("approval_policy", Object()),
                ("terminals", new NativeJsonArray([Object(
                    ("terminal_id", new NativeJsonString("terminal-91")),
                    ("cwd", new NativeJsonString(@"C:\workspace\terminal-73")),
                    ("screen", new NativeJsonString("raw-\u001b[31mred\u001b[0m-한글")),
                    ("display", new NativeJsonString("raw-red-한글")),
                    ("output_sequence", new NativeJsonInteger(19)),
                    ("state", new NativeJsonString("running")),
                    ("exit_status", NativeJsonNull.Value),
                    ("columns", new NativeJsonInteger(137)),
                    ("rows", new NativeJsonInteger(43)),
                    ("read_only", new NativeJsonBoolean(true))) ])),
                ("instance_id", new NativeJsonString("abcdef0123456789abcdef0123456789")),
                ("reset_reason", new NativeJsonString("initial")))),
            new NativeReadyIdentity(
                "terminal-session-29",
                "abcdef0123456789abcdef0123456789",
                "0.4.276"));

        // When
        var presentation = WorkspaceSnapshotPresentation.FromProjection(store.State!, "loopback");

        // Then
        Assert.IsTrue(
            presentation.Terminal.IsAvailable,
            "terminal presenter must become available when canonical terminal projection exists");
        Assert.AreEqual(1, presentation.Terminal.SourceCount);
        Assert.AreEqual("terminal-91", Property(presentation.Terminal, "TerminalId"));
        Assert.AreEqual("raw-red-한글", Property(presentation.Terminal, "Display"));
        Assert.AreEqual(true, Property(presentation.Terminal, "IsReadOnly"));
        Assert.AreEqual("running", Property(presentation.Terminal, "State"));
        Assert.AreEqual(19L, Property(presentation.Terminal, "OutputSequence"));
        Assert.AreEqual(137L, Property(presentation.Terminal, "Columns"));
        Assert.AreEqual(43L, Property(presentation.Terminal, "Rows"));
        Assert.IsFalse(presentation.Terminal.GetType().GetProperties()
            .Any(property => property.Name.Contains("Lease", StringComparison.OrdinalIgnoreCase)));

        var workflowType = typeof(TerminalWorkflowPresentation);
        var expectedProperties = new (string Name, Type Type)[]
        {
            ("CreateAvailability", typeof(MutationAvailability)),
            ("WorkspaceCwd", typeof(string)),
            ("TerminalId", typeof(string)),
            ("DraftInput", typeof(string)),
            ("PendingCommandId", typeof(string)),
            ("PendingCommandType", typeof(string)),
            ("CommandState", typeof(TerminalCommandState)),
            ("AcceptedCursor", typeof(long?)),
            ("CurrentCursor", typeof(long?)),
            ("NextInputSequence", typeof(long)),
            ("ApprovalId", typeof(string)),
            ("RefusalCode", typeof(string)),
            ("UserFacingFailure", typeof(string)),
            ("MutationAvailability", typeof(TerminalMutationAvailability)),
        };
        var properties = workflowType.GetProperties(
            System.Reflection.BindingFlags.Public |
            System.Reflection.BindingFlags.Instance |
            System.Reflection.BindingFlags.DeclaredOnly)
            .Where(property => property.SetMethod is not null)
            .ToArray();
        CollectionAssert.AreEqual(
            expectedProperties.Select(expected => expected.Name).ToArray(),
            properties.Select(property => property.Name).ToArray());
        CollectionAssert.AreEqual(
            expectedProperties.Select(expected => expected.Type).ToArray(),
            properties.Select(property => property.PropertyType).ToArray());
        Assert.IsTrue(properties.All(property => property.SetMethod?.ReturnParameter
            .GetRequiredCustomModifiers()
            .Contains(typeof(System.Runtime.CompilerServices.IsExternalInit)) == true));
        var constructors = workflowType.GetConstructors();
        Assert.AreEqual(1, constructors.Length);
        Assert.AreEqual(0, constructors[0].GetParameters().Length);
        Assert.IsFalse(workflowType.GetMethods().Any(method => method.Name == "Deconstruct"));

        var empty = TerminalWorkflowPresentation.Empty;
        Assert.AreEqual(
            JsonSerializer.Serialize(new
            {
                CreateAvailability = new MutationAvailability(false, "E_CONNECTION_NOT_READY"),
                WorkspaceCwd = (string?)null,
                TerminalId = (string?)null,
                DraftInput = string.Empty,
                PendingCommandId = (string?)null,
                PendingCommandType = (string?)null,
                CommandState = TerminalCommandState.Idle,
                AcceptedCursor = (long?)null,
                CurrentCursor = (long?)null,
                NextInputSequence = 1L,
                ApprovalId = (string?)null,
                RefusalCode = (string?)null,
                UserFacingFailure = (string?)null,
                MutationAvailability = TerminalMutationAvailability.None,
                HasPendingCommand = false,
            }),
            JsonSerializer.Serialize(empty));
        var changed = empty with { DraftInput = "echo nominal" };
        Assert.AreEqual(string.Empty, empty.DraftInput);
        Assert.AreEqual("echo nominal", changed.DraftInput);

        var begun = changed.Begin("command-nominal", "terminal.input");
        Assert.AreEqual(TerminalCommandState.PendingReceipt, begun.CommandState);
        Assert.AreEqual("command-nominal", begun.PendingCommandId);
        var accepted = begun.Accept("command-nominal", 72, "terminal-nominal", 4);
        Assert.AreEqual(TerminalCommandState.AcceptedPendingProjection, accepted.CommandState);
        Assert.AreEqual("terminal-nominal", accepted.TerminalId);
        Assert.AreEqual(72L, accepted.AcceptedCursor);
        Assert.AreEqual(4L, accepted.NextInputSequence);
        var resolved = accepted.Resolve("command-nominal", false, 73);
        Assert.AreEqual(TerminalCommandState.Idle, resolved.CommandState);
        Assert.IsNull(resolved.PendingCommandId);
        Assert.AreEqual(73L, resolved.CurrentCursor);
        var refused = empty.Begin("command-refused", "terminal.create").Refuse(
            new NativeTerminalRefusal(
                "E_TERMINAL_APPROVAL_REQUIRED",
                "command-refused",
                74,
                "approval-nominal",
                "Approval is required."));
        Assert.AreEqual(TerminalCommandState.ApprovalRequired, refused.CommandState);
        Assert.AreEqual("approval-nominal", refused.ApprovalId);
        var cleared = (resolved with
        {
            WorkspaceCwd = @"C:\workspace\terminal-73",
            MutationAvailability = new TerminalMutationAvailability(
                new MutationAvailability(true, null),
                new MutationAvailability(true, null),
                new MutationAvailability(true, null),
                new MutationAvailability(true, null)),
        }).ClearAuthority();
        Assert.IsNull(cleared.WorkspaceCwd);
        Assert.IsNull(cleared.TerminalId);
        Assert.AreEqual(TerminalMutationAvailability.None, cleared.MutationAvailability);
    }

    [TestMethod]
    public void TerminalPresentation_WhenLegacyTupleIsNotFalseZero_RejectsIt()
    {
        // Given the only shipped compatibility tuple and representative invalid tuples
        (bool IsAvailable, int SourceCount)[] invalid =
            [(true, 0), (false, 1), (true, 1), (false, -1)];

        // When legacy construction is attempted, Then only (false, 0) maps to canonical state
        foreach (var tuple in invalid)
        {
            _ = Assert.ThrowsException<ArgumentException>(
                () => new TerminalPresentation(tuple.IsAvailable, tuple.SourceCount));
        }

        var compatible = new TerminalPresentation(false, 0);
        Assert.IsFalse(compatible.IsCreateEnabled);
        Assert.AreEqual("E_COMMAND_UNADVERTISED", compatible.DisabledReason);
        Assert.AreEqual(0, compatible.Items.Count);
    }

    private static object? Property(object target, string name)
    {
        var property = target.GetType().GetProperty(name);
        Assert.IsNotNull(property, $"terminal presenter must expose {name}");
        return property.GetValue(target);
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
