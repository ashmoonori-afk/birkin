using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Shell.Lifecycle;

public enum BridgeStartupFailureReason
{
    CliUnavailable,
    CliFailed,
    CliCrashLoop,
    CliTimedOut,
}

public abstract record BridgeStartupResult
{
    private BridgeStartupResult()
    {
    }

    public sealed record OwnedReady(
        string AnnouncementJson,
        IBridgeProcess Process) : BridgeStartupResult;

    public sealed record AttachedReady(
        string AnnouncementJson,
        BridgeAnnouncement Announcement) : BridgeStartupResult;

    public sealed record Failed(BridgeStartupFailureReason Reason) : BridgeStartupResult;
}

public static class BridgeStartup
{
    private static readonly TimeSpan AnnouncementTimeout =
        TimeSpan.FromSeconds(15);

    public static Task<BridgeStartupResult> StartOwnedAsync(
        BridgeSupervisor supervisor,
        CancellationToken cancellationToken) =>
        StartOwnedAsync(
            supervisor,
            AnnouncementTimeout,
            cancellationToken);

    public static async Task<BridgeStartupResult> StartOwnedAsync(
        BridgeSupervisor supervisor,
        TimeSpan announcementTimeout,
        CancellationToken cancellationToken)
    {
        while (true)
        {
            var process = supervisor.OwnedProcess;
            if (process is not IBridgeAnnouncementSource)
            {
                if (!supervisor.StartOwnedIfNeeded()
                    || supervisor.OwnedProcess is not
                        IBridgeAnnouncementSource)
                {
                    return new BridgeStartupResult.Failed(
                        FailureReason(supervisor.StopReason));
                }
                process = supervisor.OwnedProcess;
            }

            if (process is null)
            {
                return new BridgeStartupResult.Failed(
                    FailureReason(supervisor.StopReason));
            }
            var result = await WaitForOwnedAsync(
                supervisor,
                process,
                announcementTimeout,
                cancellationToken).ConfigureAwait(false);
            var current = supervisor.OwnedProcess;
            if (current is not null
                && !ReferenceEquals(current, process))
            {
                continue;
            }
            if (current is null
                && supervisor.StopReason is { } stopReason)
            {
                return new BridgeStartupResult.Failed(
                    FailureReason(stopReason));
            }
            return result;
        }
    }

    public static Task<BridgeStartupResult> WaitForOwnedAsync(
        BridgeSupervisor supervisor,
        IBridgeProcess process,
        CancellationToken cancellationToken) =>
        WaitForOwnedAsync(
            supervisor,
            process,
            AnnouncementTimeout,
            cancellationToken);

    public static async Task<BridgeStartupResult> WaitForOwnedAsync(
        BridgeSupervisor supervisor,
        IBridgeProcess process,
        TimeSpan announcementTimeout,
        CancellationToken cancellationToken)
    {
        if (process is not IBridgeAnnouncementSource source)
        {
            _ = await supervisor
                .StopOwnedAsync(process, BridgeStopReason.StartupFailed)
                .ConfigureAwait(false);
            return new BridgeStartupResult.Failed(
                BridgeStartupFailureReason.CliFailed);
        }
        try
        {
            var announcement = await source
                .ReadAnnouncementAsync(cancellationToken)
                .AsTask()
                .WaitAsync(announcementTimeout, cancellationToken)
                .ConfigureAwait(false);
            return new BridgeStartupResult.OwnedReady(
                announcement,
                process);
        }
        catch (TimeoutException)
        {
            _ = await supervisor
                .StopOwnedAsync(process, BridgeStopReason.StartupTimeout)
                .ConfigureAwait(false);
            return new BridgeStartupResult.Failed(
                BridgeStartupFailureReason.CliTimedOut);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            _ = await supervisor
                .StopOwnedAsync(process, BridgeStopReason.StartupFailed)
                .ConfigureAwait(false);
            return new BridgeStartupResult.Failed(
                BridgeStartupFailureReason.CliFailed);
        }
    }

    public static BridgeStartupFailureReason FailureReason(
        BridgeStopReason? stopReason) =>
        stopReason switch
        {
            BridgeStopReason.LaunchFailed =>
                BridgeStartupFailureReason.CliUnavailable,
            BridgeStopReason.CrashLoop =>
                BridgeStartupFailureReason.CliCrashLoop,
            BridgeStopReason.StartupTimeout =>
                BridgeStartupFailureReason.CliTimedOut,
            _ => BridgeStartupFailureReason.CliFailed,
        };

    public static BridgeStartupResult ParseAttached(string announcementJson)
    {
        try
        {
            var announcement = BridgeAnnouncement.Parse(announcementJson);
            return new BridgeStartupResult.AttachedReady(
                announcementJson,
                announcement);
        }
        catch (NativeProtocolError)
        {
            return new BridgeStartupResult.Failed(
                BridgeStartupFailureReason.CliFailed);
        }
    }
}
