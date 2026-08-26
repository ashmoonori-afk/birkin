using Birkin.Native.Protocol.Transport;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Lifecycle;

namespace Birkin.Native.App.Startup;

public sealed class DevelopmentPreviewRunner
{
    private readonly ShellCoordinator _coordinator;
    private readonly BridgeSession _session;
    private readonly BridgeSupervisor _supervisor;
    private readonly string _productVersion;
    private CancellationToken _lifetime;
    private Task _replacement = Task.CompletedTask;
    private bool _ownedConnectionStarted;

    public DevelopmentPreviewRunner(
        ShellCoordinator coordinator,
        BridgeSession session,
        BridgeSupervisor supervisor,
        string productVersion)
    {
        _coordinator = coordinator;
        _session = session;
        _supervisor = supervisor;
        _productVersion = productVersion;
        _supervisor.OwnedProcessStarted += OnOwnedProcessStarted;
    }

    public async Task RunAsync(AppOptions options, CancellationToken cancellationToken)
    {
        _lifetime = cancellationToken;
        if (options.IsAttached)
        {
            var announcementJson = options.BridgeAnnouncementJson;
            var announcement = BridgeAnnouncement.Parse(announcementJson);
            _supervisor.AttachExisting(announcement);
            await _coordinator.ConnectAsync(
                announcementJson,
                _productVersion,
                cancellationToken).ConfigureAwait(false);
            return;
        }

        if (!_supervisor.StartOwnedIfNeeded()
            || _supervisor.OwnedProcess is not IBridgeAnnouncementSource source)
        {
            throw new InvalidOperationException("The owned native bridge could not be started.");
        }

        var ownedAnnouncement = await source.ReadAnnouncementAsync(cancellationToken).ConfigureAwait(false);
        await _coordinator.ConnectAsync(
            ownedAnnouncement,
            _productVersion,
            cancellationToken).ConfigureAwait(false);
        _ownedConnectionStarted = true;
    }

    internal async ValueTask StopObservingOwnedProcessAsync()
    {
        _supervisor.OwnedProcessStarted -= OnOwnedProcessStarted;
        try
        {
            await _replacement.ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
        }
    }

    private void OnOwnedProcessStarted(IBridgeProcess process)
    {
        if (!_ownedConnectionStarted || process is not IBridgeAnnouncementSource source)
        {
            return;
        }

        _replacement = ReconnectToReplacementAsync(source);
    }

    private async Task ReconnectToReplacementAsync(IBridgeAnnouncementSource source)
    {
        try
        {
            var announcementJson = await source.ReadAnnouncementAsync(_lifetime).ConfigureAwait(false);
            var announcement = BridgeAnnouncement.Parse(announcementJson);
            await _session.ReconnectAsync(
                announcement,
                _productVersion,
                _lifetime).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
        }
    }
}
