using System.Text;
using System.Text.Json;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Protocol.Tests.Projection;

[TestClass]
public sealed class NativeProjectionEventTests
{
    private static readonly NativeReadyIdentity ReadyIdentity = new("session-1", "instance-1", "fixture-version");

    [TestMethod]
    public void ApplyEvent_WhenPythonEventsAreContiguous_MatchesEveryExpectedProjection()
    {
        // Given
        using var fixture = LoadFixture();
        var store = new NativeProjectionStore();
        store.ApplySnapshot(Decode(fixture.RootElement.GetProperty("snapshot")), ReadyIdentity);
        var consumed = 0;

        // When / Then
        foreach (var vector in fixture.RootElement.GetProperty("events").EnumerateArray())
        {
            store.ApplyEvent(Decode(vector));
            consumed++;

            var expected = NormalizeLegacyTerminalFixture(NativeJsonParser.Parse(Encoding.UTF8.GetBytes(
                vector.GetProperty("expected_state").GetRawText())));
            var state = store.State;
            Assert.IsNotNull(state);
            CollectionAssert.AreEqual(
                NativeJsonSerializer.Serialize(expected),
                NativeJsonSerializer.Serialize(StateJson(state)),
                $"cursor {vector.GetProperty("cursor").GetInt64()}");
            Assert.AreEqual(vector.GetProperty("cursor").GetInt64(), state.Cursor);
            Assert.AreEqual(NativeProjectionStoreStatus.Current, store.Status);
        }

        Assert.AreEqual(14, consumed);
    }

    [TestMethod]
    public void ApplyEvent_WhenTerminalOutputContainsSplitVtAndCjk_DerivesOrderedDisplayWithoutLease()
    {
        // Given
        var store = TerminalStore(41);
        store.ApplyEvent(TerminalEvent(
            42,
            "terminal.opened",
            Object(
                ("terminal_id", new NativeJsonString("terminal-73")),
                ("cwd", new NativeJsonString("C:/workspace/non-default-73")),
                ("lease", new NativeJsonString("lease-must-not-project-8642")))));

        // When
        store.ApplyEvent(TerminalEvent(43, "terminal.output", Output("terminal-73", 1, "start-\u001b[3")));
        store.ApplyEvent(TerminalEvent(44, "terminal.output", Output("terminal-73", 2, "1m한")));
        store.ApplyEvent(TerminalEvent(45, "terminal.output", Output("terminal-73", 3, "글\u001b[0m-end")));

        // Then
        var terminal = Terminal(store);
        Assert.AreEqual("start-\u001b[31m한글\u001b[0m-end", String(terminal, "screen"));
        Assert.AreEqual("start-한글-end", String(terminal, "display"));
        Assert.AreEqual(3L, Integer(terminal, "output_sequence"));
        Assert.IsFalse(terminal.ContainsKey("lease"));
        Assert.IsTrue(Boolean(terminal, "read_only"));
    }

    [TestMethod]
    public void ApplyEvent_WhenWindowsStartupVtAndCwdArePresent_ProjectsSafeDisplay()
    {
        // Given
        const string cwd = @"C:\Users\owner\AppData\Local\Temp\workspace";
        const string raw = "\u001b[?9001h\u001b[?1004h\u001b[?25l"
            + "\u001b]0;C:\\Users\\owner\\AppData\\Local\\Temp\\workspace\\python.exe\u0007"
            + "\u001b[2J\u001b[H\u001b[32m" + cwd + "> 한글-日本語\u001b[0m\u001b[?25h";
        var store = TerminalStore(71);
        store.ApplyEvent(TerminalEvent(
            72,
            "terminal.opened",
            Object(
                ("terminal_id", new NativeJsonString("terminal-startup-73")),
                ("cwd", new NativeJsonString(cwd)))));

        // When
        store.ApplyEvent(TerminalEvent(
            73,
            "terminal.output",
            Output("terminal-startup-73", 1, raw)));

        // Then
        var terminal = Terminal(store);
        Assert.AreEqual(raw, String(terminal, "screen"));
        Assert.AreEqual("[workspace]> 한글-日本語", String(terminal, "display"));
        Assert.IsFalse(String(terminal, "display").Contains('\u001b'));
        Assert.IsFalse(String(terminal, "display").Contains("&gt;", StringComparison.Ordinal));
        Assert.IsFalse(String(terminal, "display").Contains(@"C:\Users\", StringComparison.OrdinalIgnoreCase));
    }

    [TestMethod]
    public void ApplyEvent_WhenTerminalOutputSequenceIsNotNext_DoesNotReorderCanonicalScreen()
    {
        // Given
        var store = TerminalStore(67);
        store.ApplyEvent(TerminalEvent(
            68,
            "terminal.opened",
            Object(("terminal_id", new NativeJsonString("terminal-order-29")))));

        // When
        store.ApplyEvent(TerminalEvent(
            69,
            "terminal.output",
            Output("terminal-order-29", 2, "must-not-append-510")));

        // Then
        var terminal = Terminal(store);
        Assert.AreEqual(string.Empty, String(terminal, "screen"));
        Assert.AreEqual(string.Empty, String(terminal, "display"));
        Assert.AreEqual(0L, Integer(terminal, "output_sequence"));
    }

    [TestMethod]
    public void ApplyEvent_WhenTerminalExits_ProjectsReadOnlyExitedStateWithoutLease()
    {
        // Given
        var store = TerminalStore(88);
        store.ApplyEvent(TerminalEvent(
            89,
            "terminal.opened",
            Object(
                ("terminal_id", new NativeJsonString("terminal-exit-47")),
                ("lease", new NativeJsonString("ephemeral-lease-204")))));

        // When
        store.ApplyEvent(TerminalEvent(
            90,
            "terminal.exited",
            Object(
                ("terminal_id", new NativeJsonString("terminal-exit-47")),
                ("exit_status", new NativeJsonInteger(73)))));

        // Then
        var terminal = Terminal(store);
        Assert.AreEqual("exited", String(terminal, "state"));
        Assert.AreEqual(73L, Integer(terminal, "exit_status"));
        Assert.IsTrue(Boolean(terminal, "read_only"));
        Assert.IsFalse(terminal.ContainsKey("lease"));
    }

    private static NativeProjectionStore TerminalStore(long cursor)
    {
        var store = new NativeProjectionStore();
        store.ApplySnapshot(new NativeEnvelope(
            NativeMessageKind.Snapshot,
            "terminal-snapshot-19",
            Object(
                ("protocol_version", new NativeJsonInteger(1)),
                ("session_id", new NativeJsonString("session-1")),
                ("cursor", new NativeJsonInteger(cursor)),
                ("panels", new NativeJsonArray([])),
                ("conversation", new NativeJsonArray([])),
                ("composer", Object(("can_interrupt", new NativeJsonBoolean(false)))),
                ("status", Object()),
                ("working_memory", Object()),
                ("approval_policy", Object()),
                ("terminals", new NativeJsonArray([])),
                ("instance_id", new NativeJsonString("instance-1")),
                ("reset_reason", new NativeJsonString("initial")))),
            ReadyIdentity);
        return store;
    }

    private static NativeEnvelope TerminalEvent(long cursor, string type, NativeJsonObject payload) => new(
        NativeMessageKind.Event,
        $"terminal-event-{cursor}",
        Object(
            ("protocol_version", new NativeJsonInteger(1)),
            ("session_id", new NativeJsonString("session-1")),
            ("cursor", new NativeJsonInteger(cursor)),
            ("event_id", new NativeJsonString($"terminal-event-id-{cursor}")),
            ("type", new NativeJsonString(type)),
            ("timestamp", new NativeJsonString("2037-04-05T06:07:08Z")),
            ("actor_id", new NativeJsonString("native-human-73")),
            ("command_id", new NativeJsonString("terminal-command-91")),
            ("payload", payload)));

    private static NativeJsonObject Output(string terminalId, long sequence, string data) => Object(
        ("terminal_id", new NativeJsonString(terminalId)),
        ("sequence", new NativeJsonInteger(sequence)),
        ("data", new NativeJsonString(data)));

    private static NativeJsonObject Terminal(NativeProjectionStore store) =>
        store.State?.Terminals.Values.Single() as NativeJsonObject
        ?? throw new AssertFailedException("one terminal projection was expected");

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));

    private static string String(NativeJsonObject value, string key) =>
        value[key] is NativeJsonString text
            ? text.Value
            : throw new AssertFailedException($"{key} must be a string");

    private static long Integer(NativeJsonObject value, string key) =>
        value[key] is NativeJsonInteger integer
            ? integer.Value
            : throw new AssertFailedException($"{key} must be an integer");

    private static bool Boolean(NativeJsonObject value, string key) =>
        value[key] is NativeJsonBoolean boolean
            ? boolean.Value
            : throw new AssertFailedException($"{key} must be a boolean");

    private static NativeJsonObject StateJson(NativeProjectionState state) => new([
        new("protocol_version", new NativeJsonInteger(state.ProtocolVersion)),
        new("session_id", new NativeJsonString(state.SessionId)),
        new("cursor", new NativeJsonInteger(state.Cursor)),
        new("panels", state.Panels),
        new("conversation", state.Conversation),
        new("composer", state.Composer),
        new("status", state.Status),
        new("working_memory", state.WorkingMemory),
        new("approval_policy", state.ApprovalPolicy),
        new("terminals", state.Terminals),
    ]);

    private static NativeJsonValue NormalizeLegacyTerminalFixture(NativeJsonValue expected)
    {
        if (expected is not NativeJsonObject body || body["terminals"] is not NativeJsonArray terminals)
        {
            return expected;
        }

        var normalized = terminals.Values.Select(value =>
        {
            var terminal = (NativeJsonObject)value;
            var screen = String(terminal, "screen");
            var cwd = String(terminal, "cwd");
            var display = TerminalVtProjection.Render(screen)
                .Replace(cwd, "[workspace]", StringComparison.OrdinalIgnoreCase);
            return new NativeJsonObject(terminal.Pairs.SelectMany(pair => pair.Key switch
            {
                "lease" or "display" => [],
                "screen" => new KeyValuePair<string, NativeJsonValue>[]
                {
                    pair,
                    new("display", new NativeJsonString(display)),
                },
                _ => [pair],
            }));
        });
        return new NativeJsonObject(body.Pairs.Select(pair => pair.Key == "terminals"
            ? new KeyValuePair<string, NativeJsonValue>(pair.Key, new NativeJsonArray(normalized))
            : pair));
    }

    private static JsonDocument LoadFixture() => JsonDocument.Parse(File.ReadAllBytes(
        Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-projection-vectors.json")));

    private static NativeEnvelope Decode(JsonElement vector) => NativeFrameCodec.Decode(
        Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!));
}
