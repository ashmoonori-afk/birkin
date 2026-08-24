using System.Reflection;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Startup;

public sealed class CompositionRoot : IAsyncDisposable
{
    private CompositionRoot(
        ShellPresentationModel presentationModel,
        ShellCoordinator coordinator,
        DevelopmentPreviewRunner runner)
    {
        PresentationModel = presentationModel;
        Coordinator = coordinator;
        Runner = runner;
    }

    public ShellPresentationModel PresentationModel { get; }

    public ShellCoordinator Coordinator { get; }

    public DevelopmentPreviewRunner Runner { get; }

    public static CompositionRoot Create(SynchronizationContext synchronizationContext)
    {
        var presentationModel = new ShellPresentationModel(synchronizationContext);
        var coordinator = new ShellCoordinator(
            new NativeClientConnection(),
            new NativeProjectionStore(),
            presentationModel);
        var informationalVersion = typeof(CompositionRoot).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
            ?? throw new InvalidOperationException("The application product version is unavailable.");
        var productVersion = informationalVersion.Split('+', 2)[0];
        return new CompositionRoot(
            presentationModel,
            coordinator,
            new DevelopmentPreviewRunner(coordinator, productVersion));
    }

    public ValueTask DisposeAsync() => Coordinator.DisposeAsync();
}
