import Darwin

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

        composer.draft = "Command after reconnect"
        guard composer.send(
            availability: availability,
            canSend: true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("post-reconnect send refused")
        }
        try await journeyDeadline("post reconnect receipt") { [events] in
            try await events.wait(for: "command-receipt", occurrence: 1)
        }
        record("post-reconnect-command", "cursor=\(cursor)")
    }
}
