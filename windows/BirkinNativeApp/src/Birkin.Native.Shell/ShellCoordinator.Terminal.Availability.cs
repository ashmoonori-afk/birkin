using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private MutationAvailability TerminalAvailabilityLocked(
        string commandType,
        string? terminalId,
        ConnectionAuthority authority)
    {
        var hasControl = string.Equals(commandType, TerminalCommands.CreateCommandType, StringComparison.Ordinal)
            || terminalId is not null && _terminalControls.ContainsKey(terminalId);
        return AvailabilityLocked(commandType, hasControl, authority);
    }

    private void RefreshTerminalAvailabilityLocked(ConnectionAuthority authority)
    {
        var terminalId = _terminalWorkflow.TerminalId;
        var create = _terminalControls.Count == 0
            ? TerminalAvailabilityLocked(TerminalCommands.CreateCommandType, null, authority)
            : new MutationAvailability(false, "E_TERMINAL_ACTIVE");
        _terminalWorkflow = _terminalWorkflow with
        {
            CreateAvailability = create,
            MutationAvailability = new TerminalMutationAvailability(
                TerminalAvailabilityLocked(TerminalCommands.InputCommandType, terminalId, authority),
                TerminalAvailabilityLocked(TerminalCommands.ResizeCommandType, terminalId, authority),
                TerminalAvailabilityLocked(TerminalCommands.SignalCommandType, terminalId, authority),
                TerminalAvailabilityLocked(TerminalCommands.CloseCommandType, terminalId, authority)),
        };
    }
}
