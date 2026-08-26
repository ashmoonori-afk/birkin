using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private sealed class TerminalLeaseControl(string lease)
    {
        public string Lease { get; } = lease;
        public long NextSequence { get; set; } = 1;
    }

    private readonly Dictionary<string, TerminalLeaseControl> _terminalControls =
        new(StringComparer.Ordinal);
    private TerminalWorkflowPresentation _terminalWorkflow = TerminalWorkflowPresentation.Empty;
    private string? _approvalCwd;
    private string? _pendingCreateCwd;

    public Task<bool> CreateTerminalAsync(string cwd, CancellationToken cancellationToken) =>
        SubmitTerminalAsync(
            TerminalCommands.CreateCommandType,
            context =>
            {
                _pendingCreateCwd = cwd;
                return TerminalCommands.Create(
                    new TerminalCreateIntent(
                        "native_human",
                        cwd,
                        string.Equals(_approvalCwd, cwd, StringComparison.Ordinal)
                            ? _terminalWorkflow.ApprovalId
                            : null),
                    context);
            },
            null,
            false,
            cancellationToken);

    public Task<bool> SendTerminalInputAsync(
        string terminalId,
        string data,
        CancellationToken cancellationToken) =>
        SubmitTerminalControlAsync(
            terminalId,
            TerminalCommands.InputCommandType,
            (control, context) => TerminalCommands.Input(
                new TerminalInputIntent(terminalId, control.Lease, control.NextSequence, data),
                context),
            true,
            cancellationToken);

    public Task<bool> ResizeTerminalAsync(
        string terminalId,
        long columns,
        long rows,
        CancellationToken cancellationToken) =>
        SubmitTerminalControlAsync(
            terminalId,
            TerminalCommands.ResizeCommandType,
            (control, context) => TerminalCommands.Resize(
                new TerminalResizeIntent(terminalId, control.Lease, columns, rows),
                context),
            false,
            cancellationToken);

    public Task<bool> InterruptTerminalAsync(
        string terminalId,
        CancellationToken cancellationToken) =>
        SubmitTerminalControlAsync(
            terminalId,
            TerminalCommands.SignalCommandType,
            (control, context) => TerminalCommands.Signal(
                new TerminalSignalIntent(terminalId, control.Lease, "INT"),
                context),
            false,
            cancellationToken);

    public Task<bool> CloseTerminalAsync(
        string terminalId,
        CancellationToken cancellationToken) =>
        SubmitTerminalControlAsync(
            terminalId,
            TerminalCommands.CloseCommandType,
            (control, context) => TerminalCommands.Close(
                new TerminalCloseIntent(terminalId, control.Lease),
                context),
            false,
            cancellationToken);

}
