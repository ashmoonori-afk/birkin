using System.Reflection;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Commands;

[TestClass]
public sealed class TerminalCommandsTests
{
    private static readonly CommandRequestContext Context =
        new("terminal-command-73", 41, "terminal-region-29");

    [TestMethod]
    public void Create_WithApprovedWorkspace_BuildsExactTypedPayload()
    {
        var request = Build(
            "Create",
            "TerminalCreateIntent",
            ["native_human", @"C:\workspace\terminal-73", "approval-terminal-8642"]);

        AssertRequest(request, "terminal.create", Object(
            ("actor_kind", new NativeJsonString("native_human")),
            ("cwd", new NativeJsonString(@"C:\workspace\terminal-73")),
            ("approval_id", new NativeJsonString("approval-terminal-8642"))));
    }

    [TestMethod]
    public void Input_WithTransientLeaseAndSequence_BuildsExactTypedPayload()
    {
        var request = Build(
            "Input",
            "TerminalInputIntent",
            ["terminal-91", "transient-lease-510", 17L, "echo 한글-日本語\r\n"]);

        AssertRequest(request, "terminal.input", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("sequence", new NativeJsonInteger(17)),
            ("data", new NativeJsonString("echo 한글-日本語\r\n"))));
    }

    [TestMethod]
    public void Resize_WithNonDefaultDimensions_BuildsExactTypedPayload()
    {
        var request = Build(
            "Resize",
            "TerminalResizeIntent",
            ["terminal-91", "transient-lease-510", 137L, 43L]);

        AssertRequest(request, "terminal.resize", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("columns", new NativeJsonInteger(137)),
            ("rows", new NativeJsonInteger(43))));
    }

    [TestMethod]
    public void Signal_WithInterrupt_BuildsExactTypedPayload()
    {
        var request = Build(
            "Signal",
            "TerminalSignalIntent",
            ["terminal-91", "transient-lease-510", "INT"]);

        AssertRequest(request, "terminal.signal", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510")),
            ("signal", new NativeJsonString("INT"))));
    }

    [TestMethod]
    public void Close_WithTransientLease_BuildsExactTypedPayload()
    {
        var request = Build(
            "Close",
            "TerminalCloseIntent",
            ["terminal-91", "transient-lease-510"]);

        AssertRequest(request, "terminal.close", Object(
            ("terminal_id", new NativeJsonString("terminal-91")),
            ("lease", new NativeJsonString("transient-lease-510"))));
    }

    private static NativeCommandRequest Build(
        string methodName,
        string intentName,
        object?[] arguments)
    {
        var assembly = typeof(ConversationCommands).Assembly;
        var commands = assembly.GetType("Birkin.Native.Shell.Commands.TerminalCommands");
        Assert.IsNotNull(commands, "Shell must provide typed TerminalCommands builders");
        var intentType = assembly.GetType($"Birkin.Native.Shell.Commands.{intentName}");
        Assert.IsNotNull(intentType, $"Shell must provide typed {intentName}");
        var intent = Activator.CreateInstance(intentType, arguments);
        Assert.IsNotNull(intent, $"{intentName} must accept the typed protocol values");
        var method = commands.GetMethod(
            methodName,
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: [intentType, typeof(CommandRequestContext)],
            modifiers: null);
        Assert.IsNotNull(method, $"TerminalCommands.{methodName} must be a typed builder");
        return (NativeCommandRequest)(method.Invoke(null, [intent, Context])
            ?? throw new AssertFailedException("terminal builder returned null"));
    }

    private static void AssertRequest(
        NativeCommandRequest request,
        string commandType,
        NativeJsonObject expectedPayload)
    {
        Assert.AreEqual("terminal-command-73", request.CommandId);
        Assert.AreEqual(41L, request.ExpectedCursor);
        Assert.AreEqual("terminal-region-29", request.ViewId);
        Assert.AreEqual(commandType, request.CommandType);
        CollectionAssert.AreEqual(
            NativeJsonSerializer.Serialize(expectedPayload),
            NativeJsonSerializer.Serialize(request.Payload));
    }

    private static NativeJsonObject Object(params (string Key, NativeJsonValue Value)[] pairs) =>
        new(pairs.Select(pair => new KeyValuePair<string, NativeJsonValue>(pair.Key, pair.Value)));
}
