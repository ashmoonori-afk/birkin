import BirkinNativeProtocol
import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveTerminal() async throws {
        let ready = try require(session, "session lost")
        var proposalRequest: NativeCommandRequest?
        guard terminal.requestTerminal(
            cwd: configuration.workspaceRoot.path,
            expectedCursor: cursor,
            sessionCapability: ready.sessionCapability,
            submit: {
                proposalRequest = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("terminal approval request refused")
        }
        let proposal = try require(proposalRequest, "terminal proposal was not submitted")
        try await journeyDeadline("terminal approval requested") { [events] in
            try await events.wait(
                for: "projection-event type=approval.requested "
                    + "command_id=\(proposal.commandID)"
            )
        }
        let approval = try require(pendingApproval(), "terminal approval card missing")
        try await journeyDeadline("terminal approval refusal") { [events] in
            try await events.wait(
                for: "command-error id=\(proposal.frameID) "
                    + "code=E_TERMINAL_APPROVAL_REQUIRED "
                    + "approval_id=\(approval.id)"
            )
        }
        try await journeyDeadline("terminal proposal outcome") { [events] in
            try await events.wait(
                for: "projection-event type=command.failed "
                    + "command_id=\(proposal.commandID)"
            )
        }
        completions += 1
        guard runtime.store.projection?.terminals.isEmpty == true else {
            throw JourneyError.refused("terminal existed before approval")
        }
        try await record(
            "terminal-approval-requested",
            "approval=\(approval.id) frame=\(proposal.frameID)"
        )
        let activityBeforeApproval = activityCount()

        var approvalRequest: NativeCommandRequest?
        guard approval.submit(
            .approve,
            availability: availability,
            commandAdvertised: ready.supportedCommands.contains("approval.answer"),
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: {
                approvalRequest = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("approval action refused")
        }
        let approved = try require(approvalRequest, "approval action was not submitted")
        try await awaitCompleted(approved, label: "approval.answer")
        try await journeyDeadline("approval answer projection") { [events] in
            try await events.wait(
                for: "projection-event type=approval.answered "
                    + "command_id=\(approved.commandID)"
            )
        }
        let approvalActivity = activityCount()
        guard approvalActivity > activityBeforeApproval else {
            throw JourneyError.refused("approval produced no Activity receipt")
        }
        try await record(
            "terminal-approval-approved",
            "approval=\(approval.id) activity_rows=\(approvalActivity)"
        )

        var createRequest: NativeCommandRequest?
        guard terminal.requestTerminal(
            cwd: configuration.workspaceRoot.path,
            approvalID: approval.id,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: {
                createRequest = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("approved terminal create refused")
        }
        let create = try require(createRequest, "approved terminal was not submitted")
        try await awaitCompleted(create, label: "terminal.create")
        let opened = try require(
            runtime.store.projection?.terminals.first, "no terminal projected"
        )
        guard let lease = opened.lease, lease != NativeRedaction.marker,
              opened.readOnly == false else {
            throw JourneyError.refused("terminal lease was not installed")
        }
        try await record(
            "terminal-create-lease",
            "terminal=\(opened.terminalID)"
        )

        var inputRequest: NativeCommandRequest?
        guard terminal.sendInput(
            "printf packaged-journey-terminal\n",
            terminal: opened,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: {
                inputRequest = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("terminal input refused")
        }
        let input = try require(inputRequest, "terminal input was not submitted")
        try await awaitCompleted(input, label: "terminal.input")
        let screen = runtime.store.projection?.terminals.first?.screen ?? ""
        guard screen.contains("packaged-journey-terminal") else {
            throw JourneyError.refused("terminal output missing: \(screen.prefix(80))")
        }
        try await record(
            "terminal-input-output",
            "screen_bytes=\(screen.utf8.count)"
        )
        try await record(
            "activity-receipts",
            "activity_rows=\(activityCount())"
        )
    }

    private func pendingApproval() -> ApprovalCardPresentation? {
        runtime.store.projection?.panels
            .first(where: { $0.key == "approvals" })?.items
            .compactMap(ApprovalCardPresentation.init)
            .last(where: { !$0.isDecided })
    }

    private func activityCount() -> Int {
        runtime.store.projection?.panels
            .first(where: { $0.key == "activity_logs" })?.items.count ?? 0
    }

    private func awaitCompleted(
        _ request: NativeCommandRequest,
        label: String
    ) async throws {
        try await journeyDeadline("\(label) receipt") { [events] in
            try await events.wait(for: "command-receipt id=\(request.frameID)")
        }
        try await journeyDeadline("\(label) outcome") { [events] in
            try await events.wait(
                for: "projection-event type=command.completed "
                    + "command_id=\(request.commandID)"
            )
        }
        completions += 1
    }
}
