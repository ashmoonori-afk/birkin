using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class CompositionRootTests
{
    [TestMethod]
    public async Task Create_GivesSessionAndCoordinatorTheExactSameProjectionStore()
    {
        await using var composition = CompositionRoot.Create(new ImmediateSynchronizationContext());

        Assert.AreSame(composition.ProjectionStore, composition.Session.ProjectionStore);
        Assert.AreSame(composition.ProjectionStore, composition.Coordinator.ProjectionStore);
    }

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
