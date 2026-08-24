using System.Diagnostics;
using System.Reflection;
using System.Runtime.CompilerServices;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Startup;

public sealed class CompositionRoot : IAsyncDisposable
{
    private static readonly ConditionalWeakTable<ShellPresentationModel, ShellCoordinator> Coordinators = new();

    private CompositionRoot(
        ShellPresentationModel presentationModel,
        NativeProjectionStore projectionStore,
        BridgeSession session,
        ShellCoordinator coordinator,
        BridgeSupervisor supervisor,
        DevelopmentPreviewRunner runner)
    {
        PresentationModel = presentationModel;
        ProjectionStore = projectionStore;
        Session = session;
        Coordinator = coordinator;
        Supervisor = supervisor;
        Runner = runner;
    }

    public ShellPresentationModel PresentationModel { get; }

    public NativeProjectionStore ProjectionStore { get; }

    public BridgeSession Session { get; }

    public ShellCoordinator Coordinator { get; }

    public BridgeSupervisor Supervisor { get; }

    public DevelopmentPreviewRunner Runner { get; }

    public static CompositionRoot Create(SynchronizationContext synchronizationContext)
    {
        var presentationModel = new ShellPresentationModel(synchronizationContext);
        var projectionStore = new NativeProjectionStore();
        var session = new BridgeSession(projectionStore);
        var coordinator = new ShellCoordinator(session, projectionStore, presentationModel);
        var informationalVersion = typeof(CompositionRoot).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
            ?? throw new InvalidOperationException("The application product version is unavailable.");
        var productVersion = informationalVersion.Split('+', 2)[0];
        BridgeSupervisor? supervisor = null;
        supervisor = new BridgeSupervisor(
            () => TimeSpan.FromSeconds((double)Stopwatch.GetTimestamp() / Stopwatch.Frequency),
            () => OwnedBridgeProcess.Start(process => supervisor!.ObserveExit(process)));
        var runner = new DevelopmentPreviewRunner(coordinator, session, supervisor, productVersion);
        Coordinators.Add(presentationModel, coordinator);
        return new CompositionRoot(
            presentationModel,
            projectionStore,
            session,
            coordinator,
            supervisor,
            runner);
    }

    internal static ShellCoordinator? CoordinatorFor(ShellPresentationModel presentationModel) =>
        Coordinators.TryGetValue(presentationModel, out var coordinator) ? coordinator : null;

    public async ValueTask DisposeAsync()
    {
        _ = Coordinators.Remove(PresentationModel);
        await Runner.StopObservingOwnedProcessAsync().ConfigureAwait(false);
        await Supervisor.ShutdownAsync(
            () => ValueTask.CompletedTask,
            Coordinator.DisposeAsync).ConfigureAwait(false);
    }
}
