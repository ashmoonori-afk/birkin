using System.Collections.Concurrent;
using System.Reflection;
using System.Runtime.ExceptionServices;
using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Connection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests;

public sealed partial class ShellCoordinatorConcurrencyTests
{
    private sealed class ConcurrentSynchronizationContext : SynchronizationContext
    {
        private readonly ConcurrentQueue<(SendOrPostCallback Callback, object? State)> _work = new();
        public override void Post(SendOrPostCallback d, object? state) => _work.Enqueue((d, state));
        public void RunAll()
        {
            while (_work.TryDequeue(out var work)) work.Callback(work.State);
        }
    }

    private sealed class ImmediateSynchronizationContext : SynchronizationContext
    {
        public override void Post(SendOrPostCallback d, object? state) => d(state);
    }

    private sealed class ReentrantSynchronizationContext(Func<Task> mutation) : SynchronizationContext
    {
        private int _reentered;
        public bool ReentrantMutationCompleted { get; private set; }

        public override void Post(SendOrPostCallback d, object? state)
        {
            if (Interlocked.Exchange(ref _reentered, 1) == 0)
            {
                ReentrantMutationCompleted = mutation().Wait(TimeSpan.FromSeconds(2));
            }
            d(state);
        }
    }
}
