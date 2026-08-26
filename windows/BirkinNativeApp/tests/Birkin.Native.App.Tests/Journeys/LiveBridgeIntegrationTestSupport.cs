namespace Birkin.Native.App.Tests.Journeys;

public sealed partial class LiveBridgeIntegrationTests
{
    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object? state) => callback(state);
    }
}
