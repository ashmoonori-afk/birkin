using Birkin.Native.Shell;
using Birkin.Native.Shell.Lifecycle;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Startup;

public sealed class DevelopmentPreviewRunner : IStartupRecovery
{
    private readonly ShellCoordinator _coordinator;
    private readonly BridgeSession _session;
    private readonly BridgeSupervisor _supervisor;
    private readonly ExecutablePathSettings _executablePathSettings;
    private readonly string _productVersion;
    private readonly object _replacementGate = new();
    private readonly List<Task<bool>> _replacementTasks = [];
    private readonly List<CancellationTokenSource>
        _replacementCancellations = [];
    private CancellationToken _lifetime;
    private Task<bool> _replacement = Task.FromResult(false);
    private TaskCompletionSource _replacementSignal =
        NewReplacementSignal();
    private CancellationTokenSource? _replacementCancellation;
    private IBridgeProcess? _replacementProcess;
    private bool _observeReplacements;

    public DevelopmentPreviewRunner(
        ShellCoordinator coordinator,
        BridgeSession session,
        BridgeSupervisor supervisor,
        ExecutablePathSettings executablePathSettings,
        string productVersion)
    {
        _coordinator = coordinator;
        _session = session;
        _supervisor = supervisor;
        _executablePathSettings = executablePathSettings;
        _productVersion = productVersion;
        _supervisor.OwnedProcessStarted += OnOwnedProcessStarted;
    }

    internal bool ShouldPresentSupervisorFailures
    {
        get
        {
            lock (_replacementGate)
            {
                return _observeReplacements;
            }
        }
    }

    public async Task<StartupFailurePresentation?> RunAsync(
        AppOptions options,
        CancellationToken cancellationToken)
    {
        _lifetime = cancellationToken;
        if (options.IsAttached)
        {
            var announcementJson = options.BridgeAnnouncementJson;
            var startup = BridgeStartup.ParseAttached(announcementJson);
            if (startup is BridgeStartupResult.Failed failure)
            {
                return StartupFailurePresentation.Create(
                    failure.Reason,
                    canRetry: false);
            }
            var ready = (BridgeStartupResult.AttachedReady)startup;
            _supervisor.AttachExisting(ready.Announcement);
            var connected = await _coordinator.ConnectAsync(
                ready.AnnouncementJson,
                _productVersion,
                cancellationToken).ConfigureAwait(false);
            return connected
                ? null
                : StartupFailurePresentation.Create(
                    BridgeStartupFailureReason.CliFailed);
        }

        return await ConnectOwnedAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<StartupFailurePresentation?> RetryAsync()
    {
        await StopObservingReplacementsAsync().ConfigureAwait(false);
        if (!_supervisor.Retry())
        {
            return StartupFailurePresentation.Create(
                BridgeStartup.FailureReason(_supervisor.StopReason));
        }

        return await ConnectOwnedAsync(_lifetime).ConfigureAwait(false);
    }

    public Task<StartupFailurePresentation?> ConfigureExecutableAndRetryAsync(
        string executablePath)
    {
        if (!_executablePathSettings.TrySet(executablePath))
        {
            return Task.FromResult<StartupFailurePresentation?>(
                StartupFailurePresentation.Create(
                    BridgeStartupFailureReason.CliUnavailable));
        }

        return RetryAsync();
    }

    private async Task<StartupFailurePresentation?> ConnectOwnedAsync(
        CancellationToken cancellationToken)
    {
        var startup = await BridgeStartup.StartOwnedAsync(
            _supervisor,
            cancellationToken).ConfigureAwait(false);
        if (startup is BridgeStartupResult.Failed failure)
        {
            return StartupFailurePresentation.Create(failure.Reason);
        }

        var ready = (BridgeStartupResult.OwnedReady)startup;
        StartObservingReplacements();
        var ownedConnected = await _coordinator.ConnectAsync(
            ready.AnnouncementJson,
            _productVersion,
            cancellationToken).ConfigureAwait(false);
        if (!ownedConnected)
        {
            if (await CurrentReplacementSucceededAsync(
                    ready.Process).ConfigureAwait(false))
            {
                return null;
            }
            var stopped = await _supervisor
                .StopOwnedAsync(
                    ready.Process,
                    BridgeStopReason.StartupFailed)
                .ConfigureAwait(false);
            if (!stopped
                && await CurrentReplacementSucceededAsync(
                    ready.Process).ConfigureAwait(false))
            {
                return null;
            }
            await StopObservingReplacementsAsync().ConfigureAwait(false);
            return StartupFailurePresentation.Create(
                BridgeStartupFailureReason.CliFailed);
        }
        return null;
    }

    internal async ValueTask StopObservingOwnedProcessAsync()
    {
        _supervisor.OwnedProcessStarted -= OnOwnedProcessStarted;
        await StopObservingReplacementsAsync().ConfigureAwait(false);
    }

    private void OnOwnedProcessStarted(IBridgeProcess process)
    {
        TaskCompletionSource signal;
        lock (_replacementGate)
        {
            if (!_observeReplacements)
            {
                return;
            }
            signal = _replacementSignal;
            _replacementSignal = NewReplacementSignal();
            _replacementProcess = process;
            if (process is not IBridgeAnnouncementSource)
            {
                _replacement = Task.FromResult(false);
                signal.TrySetResult();
                return;
            }
            _replacementCancellation?.Cancel();
            var cancellation = CancellationTokenSource.CreateLinkedTokenSource(
                _lifetime);
            _replacementCancellation = cancellation;
            _replacementCancellations.Add(cancellation);
            _replacement = ReconnectToReplacementAsync(
                process,
                cancellation.Token);
            _replacementTasks.Add(_replacement);
        }
        signal.TrySetResult();
    }

    private async Task<bool> ReconnectToReplacementAsync(
        IBridgeProcess process,
        CancellationToken cancellationToken)
    {
        try
        {
            if (!_supervisor.OwnsProcess(process))
            {
                return false;
            }
            var startup = await BridgeStartup.WaitForOwnedAsync(
                _supervisor,
                process,
                cancellationToken).ConfigureAwait(false);
            if (startup is not BridgeStartupResult.OwnedReady ready)
            {
                return false;
            }
            if (!_supervisor.OwnsProcess(process))
            {
                return false;
            }
            var announcement = BridgeAnnouncement.Parse(
                ready.AnnouncementJson);
            await _session.ReconnectAsync(
                announcement,
                _productVersion,
                cancellationToken).ConfigureAwait(false);
            return _supervisor.OwnsProcess(process);
        }
        catch (OperationCanceledException)
            when (cancellationToken.IsCancellationRequested)
        {
            return false;
        }
        catch (Exception)
        {
            _ = await _supervisor
                .StopOwnedAsync(
                    process,
                    BridgeStopReason.StartupFailed)
                .ConfigureAwait(false);
            return false;
        }
    }

    private void StartObservingReplacements()
    {
        lock (_replacementGate)
        {
            _observeReplacements = true;
        }
    }

    private async Task StopObservingReplacementsAsync()
    {
        CancellationTokenSource[] cancellations;
        Task<bool>[] replacements;
        TaskCompletionSource signal;
        lock (_replacementGate)
        {
            _observeReplacements = false;
            _replacementCancellation?.Cancel();
            signal = _replacementSignal;
            _replacementSignal = NewReplacementSignal();
            cancellations = _replacementCancellations.ToArray();
            replacements = _replacementTasks.ToArray();
        }
        signal.TrySetResult();
        try
        {
            await Task.WhenAll(replacements).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
        }
        catch (Exception)
        {
            // BridgeSupervisor owns replacement failure and crash-loop state.
        }
        lock (_replacementGate)
        {
            _replacementTasks.Clear();
            _replacementCancellations.Clear();
            _replacementCancellation = null;
            _replacementProcess = null;
            _replacement = Task.FromResult(false);
        }
        foreach (var cancellation in cancellations)
        {
            cancellation.Dispose();
        }
    }

    private async Task<bool> CurrentReplacementSucceededAsync(
        IBridgeProcess originalProcess)
    {
        while (true)
        {
            IBridgeProcess? attemptedProcess = null;
            Task<bool>? replacement = null;
            Task signal;
            lock (_replacementGate)
            {
                var current = _supervisor.OwnedProcess;
                if (current is null
                    || ReferenceEquals(current, originalProcess))
                {
                    return false;
                }
                signal = _replacementSignal.Task;
                if (ReferenceEquals(current, _replacementProcess))
                {
                    attemptedProcess = current;
                    replacement = _replacement;
                }
            }
            if (replacement is null)
            {
                await signal.WaitAsync(_lifetime).ConfigureAwait(false);
                continue;
            }
            if (await replacement.ConfigureAwait(false))
            {
                return true;
            }
            if (attemptedProcess is not null
                && _supervisor.OwnsProcess(attemptedProcess))
            {
                return false;
            }
        }
    }

    private static TaskCompletionSource NewReplacementSignal() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);
}
