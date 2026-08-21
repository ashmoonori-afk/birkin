import Darwin
import BirkinNativeProtocol
import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveRecovery() async throws {
        let pid = try require(runtime.ownedBridgeProcessIdentifier, "no owned bridge")
        _ = kill(pid, SIGKILL)
        try await journeyDeadline("owned bridge restart") { [events] in
            try await events.wait(for: "bridge-restarted kind=owned")
        }
        try await journeyDeadline("replay") { [events] in
            try await events.wait(for: "replayed")
        }
        let restarted = try require(
            runtime.ownedBridgeProcessIdentifier, "no restarted bridge"
        )
        guard restarted != pid else {
            throw JourneyError.refused("bridge pid did not change")
        }
        record("owned-bridge-restart-replay", "pid=\(pid)->\(restarted)")

        let replayedTerminal = try require(
            runtime.store.projection?.terminals.first,
            "terminal missing from replay"
        )
        guard replayedTerminal.readOnly, replayedTerminal.lease == nil else {
            throw JourneyError.refused("replayed terminal retained mutation authority")
        }
        var replayInputSubmitted = false
        let replayInputAccepted = terminal.sendInput(
            "printf replay-bypass\n",
            terminal: replayedTerminal,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: {
                replayInputSubmitted = true
                self.runtime.submit($0)
            }
        )
        guard !replayInputAccepted, !replayInputSubmitted else {
            throw JourneyError.refused("replayed terminal accepted stale input")
        }
        record(
            "terminal-replay-refusal",
            "terminal=\(replayedTerminal.terminalID) read_only=true"
        )

        composer.draft = "Command after reconnect"
        var submitted: NativeCommandRequest?
        guard composer.send(
            availability: availability,
            canSend: runtime.store.projection?.composer.canSend == true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: {
                submitted = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("post-reconnect send refused")
        }
        let request = try require(submitted, "post-reconnect command was not submitted")
        try await journeyDeadline("post reconnect receipt") { [events] in
            try await events.wait(for: "command-receipt id=\(request.frameID)")
        }
        try await journeyDeadline("post reconnect outcome") { [events] in
            try await events.wait(
                forAnyOf: [
                    "projection-event type=command.completed command_id=\(request.commandID)",
                    "projection-event type=command.failed command_id=\(request.commandID)",
                ],
                occurrence: 1
            )
        }
        record(
            "post-reconnect-command",
            "frame=\(request.frameID) command=\(request.commandID) cursor=\(cursor)"
        )
    }
}
