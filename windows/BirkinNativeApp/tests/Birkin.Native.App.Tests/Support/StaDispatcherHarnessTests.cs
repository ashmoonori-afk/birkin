using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

[TestClass]
public sealed class StaDispatcherHarnessTests
{
    [TestMethod]
    public async Task InvokeAsync_WhenDelegateYields_DoesNotCompleteBeforeDelegate()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);

        var invocation = sta.InvokeAsync(async () =>
        {
            entered.TrySetResult();
            await release.Task.WaitAsync(deadline.Token);
        });
        await entered.Task.WaitAsync(deadline.Token);

        Assert.IsFalse(
            invocation.IsCompleted,
            "the dispatcher invocation completed while its async delegate was still running");
        release.TrySetResult();
        await invocation.WaitAsync(deadline.Token);
    }
}
