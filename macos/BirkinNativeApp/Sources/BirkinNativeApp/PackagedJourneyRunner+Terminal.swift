import BirkinNativeProtocol

extension PackagedJourneyRunner {
    func driveTerminal() async throws {
        guard terminal.requestTerminal(
            cwd: configuration.workspaceRoot.path,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("terminal create refused")
        }
        try await nextOutcome("terminal.create")
        let opened = try require(
            runtime.store.projection?.terminals.first, "no terminal projected"
        )
        guard let lease = opened.lease, lease != NativeRedaction.marker,
              opened.readOnly == false else {
            throw JourneyError.refused("terminal lease was not installed")
        }
        record("terminal-create-lease", "terminal=\(opened.terminalID)")

        guard terminal.sendInput(
            "printf packaged-journey-terminal\n",
            terminal: opened,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("terminal input refused")
        }
        try await nextOutcome("terminal.input")
        let screen = runtime.store.projection?.terminals.first?.screen ?? ""
        guard screen.contains("packaged-journey-terminal") else {
            throw JourneyError.refused("terminal output missing: \(screen.prefix(80))")
        }
        record("terminal-input-output", "screen_bytes=\(screen.utf8.count)")

        let activity = runtime.store.projection?
            .panels.first(where: { $0.key == "activity_logs" })?.items.count ?? 0
        record("activity-receipts", "activity_rows=\(activity)", shot: false)
    }
}
