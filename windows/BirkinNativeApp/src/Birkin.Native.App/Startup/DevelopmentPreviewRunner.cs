using Birkin.Native.Shell;

namespace Birkin.Native.App.Startup;

public sealed class DevelopmentPreviewRunner
{
    private readonly ShellCoordinator _coordinator;
    private readonly string _productVersion;

    public DevelopmentPreviewRunner(ShellCoordinator coordinator, string productVersion)
    {
        _coordinator = coordinator;
        _productVersion = productVersion;
    }

    public Task RunAsync(AppOptions options, CancellationToken cancellationToken) =>
        _coordinator.ConnectAsync(options.BridgeAnnouncementJson, _productVersion, cancellationToken);
}
