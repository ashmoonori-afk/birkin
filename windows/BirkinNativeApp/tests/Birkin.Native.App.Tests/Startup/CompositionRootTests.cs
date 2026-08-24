using System.Reflection;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Startup;

[TestClass]
public sealed class CompositionRootTests
{
    [TestMethod]
    public async Task Create_WhenNativeGraphIsComposed_SharesOneProjectionStore()
    {
        // Given
        await using var composition = CompositionRoot.Create(new ImmediateSynchronizationContext());

        // When
        var coordinatorStore = Field(composition.Coordinator, "_projectionStore");
        var connection = Field(composition.Coordinator, "_connection");
        var connectionStore = Field(connection, "_projectionStore");

        // Then
        Assert.AreSame(coordinatorStore, connectionStore);
    }

    private static object Field(object target, string name) =>
        target.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new AssertFailedException($"Expected private field {name} on {target.GetType().Name}.");

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
