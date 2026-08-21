import BirkinNativeProtocol
import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveSessionAndChat(_ ready: NativeReadySession) async throws {
        // The New Session control, gated by what Python advertises.
        if ready.supportedCommands.contains("session.create") {
            runtime.submit(ShellMutationControl.newSession)
            try await nextOutcome("session.create")
            record("session-create", "submitted=true")
        } else {
            record(
                "session-select",
                "advertised_session=\(ready.currentSessionID) create_advertised=false"
            )
        }

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
