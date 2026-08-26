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
    public async Task TerminalCreateAvailability_RequiresLiveAdvertisedCapabilityAndProjectionAuthority()
    {
        await using var fixture = await Fixture.CreateAsync(new HashSet<string>());

        AssertAvailability(fixture.Model, "CreateAvailability", false, "E_COMMAND_UNADVERTISED");
        fixture.Connection.AdvertisedCommands = ShellCoordinatorTerminalTestSupport.Commands("terminal.create");
        fixture.Store.MarkMutationAuthorityUnavailable();
        fixture.Drain();
        AssertAvailability(fixture.Model, "CreateAvailability", false, "E_PROJECTION_FORBIDS_MUTATION");
        fixture.Store.ApplySnapshot(
            Snapshot(52),
            new NativeReadyIdentity("session-1", InstanceId, "0.4.276"));
        fixture.Drain();
        AssertAvailability(fixture.Model, "CreateAvailability", true, null);
        fixture.Connection.IsCapabilityLive = false;

        Assert.IsFalse(await InvokeAsync(
            fixture.Coordinator,
            "CreateTerminalAsync",
            @"C:\workspace\capability-73",
            CancellationToken.None));
        fixture.Drain();
        Assert.AreEqual(0, fixture.Connection.Sent.Count);
        AssertAvailability(fixture.Model, "CreateAvailability", false, "E_CAPABILITY_EXPIRED");
    }
}
