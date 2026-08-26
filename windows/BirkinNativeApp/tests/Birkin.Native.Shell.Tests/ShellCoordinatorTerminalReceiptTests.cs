using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using static Birkin.Native.Shell.Tests.ShellCoordinatorTerminalTestSupport;

namespace Birkin.Native.Shell.Tests;

public sealed partial class ShellCoordinatorTerminalTests
{
    [TestMethod]
    public async Task Create_WhenApprovalRequired_PresentsTypedStateAndRetriesWithApprovalId()
    {
        await using var fixture = await Fixture.CreateAsync(ShellCoordinatorTerminalTestSupport.Commands("terminal.create"));
        fixture.Connection.Enqueue(Refusal(
            "E_TERMINAL_APPROVAL_REQUIRED",
            "terminal-create-73",
            null,
            "approval-terminal-8642",
            "internal approval path must not render"));

        Assert.IsFalse(await InvokeAsync(
            fixture.Coordinator,
            "CreateTerminalAsync",
            @"C:\workspace\approval-47",
            CancellationToken.None));
        fixture.Drain();
        AssertState(fixture.Model, "ApprovalRequired");
        Assert.AreEqual(
            "approval-terminal-8642",
            StringProperty(TerminalWorkflow(fixture.Model), "ApprovalId"));
        Assert.AreNotEqual(
            "internal approval path must not render",
            StringProperty(TerminalWorkflow(fixture.Model), "UserFacingFailure"));

        fixture.Connection.Enqueue(Receipt("terminal-input-29", 52, Object(
            ("terminal_id", new NativeJsonString("terminal-510")),
            ("lease", new NativeJsonString("transient-lease-204")))));
        Assert.IsTrue(await InvokeAsync(
            fixture.Coordinator,
            "CreateTerminalAsync",
            @"C:\workspace\approval-47",
            CancellationToken.None));
        Assert.AreEqual(
            "approval-terminal-8642",
            String(fixture.Connection.Sent[^1].Payload, "approval_id"));
    }
    [TestMethod]
    public async Task TerminalRefusal_PresentsBoundedHumanSafeFailureWithoutLeaseOrTransportText()
    {
        await using var fixture = await Fixture.WithTerminalAsync();
        fixture.Connection.Enqueue(Refusal(
            "E_TERMINAL_LEASE_REQUIRED",
            "terminal-input-29",
            null,
            null,
            "transient-lease-510 at C:\\private\\authority"));

        Assert.IsFalse(await InvokeAsync(
            fixture.Coordinator,
            "SendTerminalInputAsync",
            "terminal-91",
            "echo refused\r\n",
            CancellationToken.None));
        fixture.Drain();

        AssertState(fixture.Model, "Refused");
        var failure = StringProperty(TerminalWorkflow(fixture.Model), "UserFacingFailure");
        Assert.IsNotNull(failure);
        Assert.IsFalse(failure.Contains("transient-lease-510", StringComparison.Ordinal));
        Assert.IsFalse(failure.Contains("C:\\private", StringComparison.Ordinal));
        AssertNoPublicLease(fixture.Model);
    }
}
