using Birkin.Native.Shell.Connection;

namespace Birkin.Native.Shell.Presentation;

public sealed record MutationAuthoritySnapshot(
    ConnectionState ConnectionState,
    bool IsCapabilityLive,
    IReadOnlySet<string> AdvertisedCommands,
    bool ProjectionPermits);

public sealed record MutationAvailability(bool IsEnabled, string? DisabledReason)
{
    public string? DisabledMessage => DisabledReason switch
    {
        null => null,
        "E_CONNECTION_NOT_READY" => "Waiting for the local workspace connection.",
        "E_CAPABILITY_EXPIRED" => "Reconnect to continue.",
        "E_COMMAND_UNADVERTISED" => "This action is unavailable in the current session.",
        "E_PROJECTION_FORBIDS_MUTATION" => "This action is unavailable while the workspace refreshes.",
        _ => "This action is currently unavailable.",
    };

    public static MutationAvailability ForCommand(
        string commandType,
        MutationAuthoritySnapshot authority)
    {
        if (authority.ConnectionState != ConnectionState.Ready)
        {
            return new(false, "E_CONNECTION_NOT_READY");
        }

        if (!authority.IsCapabilityLive)
        {
            return new(false, "E_CAPABILITY_EXPIRED");
        }

        if (!authority.AdvertisedCommands.Contains(commandType))
        {
            return new(false, "E_COMMAND_UNADVERTISED");
        }

        return authority.ProjectionPermits
            ? new(true, null)
            : new(false, "E_PROJECTION_FORBIDS_MUTATION");
    }
}
