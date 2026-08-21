import BirkinNativeProtocol
import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveSessionAndChat(_ ready: NativeReadySession) async throws {
        // The New Session control is real only when Python advertises it and
        // projects the exact created identity for this command.
        guard ready.supportedCommands.contains("session.create") else {
            throw JourneyError.refused("session.create was not advertised")
        }
        let create = runtime.command(for: .newSession, session: ready)
        guard case .string(let createdSessionID) = create.payload["session_id"] else {
            throw JourneyError.refused("session.create carried no session_id")
        }
        runtime.submit(create)
        try await journeyDeadline("session.create receipt") { [events] in
            try await events.wait(for: "command-receipt id=\(create.frameID)")
        }
        try await journeyDeadline("session.create effect") { [events] in
            try await events.wait(
                for: "projection-event type=session.created "
                    + "command_id=\(create.commandID) "
                    + "subject_session_id=\(createdSessionID)"
            )
        }
        try await journeyDeadline("session.create outcome") { [events] in
            try await events.wait(
                for: "projection-event type=command.completed "
                    + "command_id=\(create.commandID)"
            )
        }
        completions += 1
        record(
            "session-create",
            "session=\(createdSessionID) frame=\(create.frameID) command=\(create.commandID)"
        )

        // The composer Send control.
        composer.draft = "Prove the packaged journey"
        guard composer.send(
            availability: availability,
            canSend: runtime.store.projection?.composer.canSend == true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("composer refused: \(composer.visibleReason ?? "")")
        }
        try await nextOutcome("chat.send")
        let conversation = runtime.store.projection?.conversation.count ?? 0
        guard conversation >= 1 else {
            throw JourneyError.refused("user message was not projected")
        }
        record(
            "chat-send-stream",
            "conversation_rows=\(conversation) outcome=\(runtime.lastCommandError == nil ? "completed" : "canonical_failure")"
        )
    }
}
