using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Messaging;
using Birkin.Native.Shell.Commands;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.Shell;

public sealed partial class ShellCoordinator
{
    private void AcceptTerminalReceipt(
        NativeEnvelope receipt,
        string commandId,
        string commandType,
        string? terminalId,
        bool incrementsSequence)
    {
        if (!string.Equals(TerminalString(receipt.Body, "command_id"), commandId, StringComparison.Ordinal))
        {
            throw new NativeProtocolError("E_CORRELATION", "receipt command does not match submitted terminal intent");
        }

        var acceptedCursor = TerminalInteger(receipt.Body, "accepted_cursor");
        var resultEventCursor = TerminalInteger(receipt.Body, "result_event_cursor");
        string? createdTerminalId = null;
        string? createdLease = null;
        if (string.Equals(commandType, TerminalCommands.CreateCommandType, StringComparison.Ordinal))
        {
            var result = TerminalObject(receipt.Body, "result");
            createdTerminalId = TerminalString(result, "terminal_id");
            createdLease = TerminalString(result, "lease");
        }

        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            var nextSequence = _terminalWorkflow.NextInputSequence;
            if (createdTerminalId is not null && createdLease is not null)
            {
                _terminalControls.Clear();
                _terminalControls.Add(createdTerminalId, new TerminalLeaseControl(createdLease));
                terminalId = createdTerminalId;
                nextSequence = 1;
                _approvalCwd = null;
                _pendingCreateCwd = null;
            }
            else if (terminalId is not null
                && incrementsSequence
                && _terminalControls.TryGetValue(terminalId, out var control))
            {
                control.NextSequence++;
                nextSequence = control.NextSequence;
            }

            if (terminalId is not null
                && string.Equals(commandType, TerminalCommands.CloseCommandType, StringComparison.Ordinal))
            {
                _terminalControls.Remove(terminalId);
            }
            _terminalWorkflow = _terminalWorkflow.Accept(
                commandId,
                acceptedCursor,
                terminalId,
                nextSequence);
            if (_projectionState?.Cursor is { } projectionCursor
                && projectionCursor >= resultEventCursor)
            {
                _terminalWorkflow = _terminalWorkflow.Resolve(commandId, false, projectionCursor);
            }
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }

    private void RefuseTerminal(NativeCommandRefusal refusal)
    {
        var approvalId = string.Equals(
            refusal.Code,
            "E_TERMINAL_APPROVAL_REQUIRED",
            StringComparison.Ordinal)
                ? refusal.ApprovalId
                : null;
        var typed = new NativeTerminalRefusal(
            refusal.Code,
            refusal.CommandId,
            refusal.CurrentCursor,
            approvalId,
            TerminalGuidance(refusal.Code));
        var authority = CaptureConnectionAuthority();
        bool drain;
        lock (_stateLock)
        {
            if (approvalId is not null
                && _terminalWorkflow.PendingCommandType == TerminalCommands.CreateCommandType)
            {
                _approvalCwd = _pendingCreateCwd;
            }
            else
            {
                _pendingCreateCwd = null;
            }
            if (refusal.Code is "E_TERMINAL_LEASE_REQUIRED" or "E_TERMINAL_LEASE_EXPIRED")
            {
                _terminalControls.Clear();
            }
            _terminalWorkflow = _terminalWorkflow.Refuse(typed);
            RefreshMutationAvailabilityLocked(authority);
            drain = EnqueuePresentationLocked(new(null, null, _workflow, _terminalWorkflow));
        }
        DrainPresentations(drain);
    }
    private static string TerminalGuidance(string code) => code switch
    {
        "E_TERMINAL_APPROVAL_REQUIRED" => "Approve this terminal launch, then try again.",
        "E_STALE_CURSOR" => "The workspace changed. Review the latest state and try again.",
        "E_TERMINAL_LEASE_REQUIRED" or "E_TERMINAL_LEASE_EXPIRED" =>
            "Terminal control expired. Create a new terminal to continue.",
        "E_TERMINAL_INPUT_SEQUENCE" => "Terminal input was out of sequence. Try again.",
        _ => "Birkin couldn't complete the terminal action. Review the workspace and try again.",
    };

    private static NativeJsonObject TerminalObject(NativeJsonObject body, string key) =>
        body[key] as NativeJsonObject
        ?? throw new NativeProtocolError("E_BODY", "terminal command result object is invalid");

    private static string TerminalString(NativeJsonObject body, string key) =>
        body[key] is NativeJsonString { Value.Length: > 0 } text
            ? text.Value
            : throw new NativeProtocolError("E_BODY", "terminal command result string is invalid");

    private static long TerminalInteger(NativeJsonObject body, string key) =>
        body[key] is NativeJsonInteger { Value: >= 0 } integer
            ? integer.Value
            : throw new NativeProtocolError("E_BODY", "terminal command result cursor is invalid");
}
