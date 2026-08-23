import Foundation
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
        try await record(
            "session-create",
            "session=\(createdSessionID) frame=\(create.frameID) command=\(create.commandID)"
        )

        // The composer Send control must complete through the configured
        // existing-account provider; fixture and error text are not evidence.
        composer.draft = PackagedProviderCompletion.prompt
        var chatRequest: NativeCommandRequest?
        guard composer.send(
            availability: availability,
            canSend: runtime.store.projection?.composer.canSend == true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: {
                chatRequest = $0
                self.runtime.submit($0)
            }
        ) else {
            throw JourneyError.refused("composer refused: \(composer.visibleReason ?? "")")
        }
        let chat = try require(chatRequest, "chat command was not submitted")
        let completedPrefix = "projection-event type=command.completed "
            + "command_id=\(chat.commandID)"
        let failedPrefix = "projection-event type=command.failed "
            + "command_id=\(chat.commandID)"
        try await journeyDeadline("chat provider outcome") { [events] in
            try await events.wait(
                forAnyOf: [completedPrefix, failedPrefix], occurrence: 1
            )
        }
        completions += 1
        guard events.recorded().contains(where: { $0.hasPrefix(completedPrefix) }) else {
            throw JourneyError.refused(
                "provider chat failed: \(runtime.lastCommandError ?? "canonical failure")"
            )
        }
        try await journeyDeadline("chat provider receipt") { [events] in
            try await events.wait(for: "command-receipt id=\(chat.frameID)")
        }
        let conversation = runtime.store.projection?.conversation ?? []
        guard PackagedProviderCompletion.validate(conversation) else {
            throw JourneyError.refused("provider completion evidence was missing or invalid")
        }
        try await record(
            "chat-send-stream",
            "conversation_rows=\(conversation.count) "
                + "provider_completion=\(PackagedProviderCompletion.marker)"
        )
    }
}

enum PackagedProviderCompletion {
    static let prompt = "Reply with exactly PACKAGED_PROVIDER_COMPLETION_OK and no other text."
    static let marker = "PACKAGED_PROVIDER_COMPLETION_OK"

    static func validate(_ conversation: [NativeJSONObject]) -> Bool {
        let rows = conversation.compactMap { row -> (String, String)? in
            guard case .string(let kind) = row["kind"],
                  case .string(let text) = row["text"] else { return nil }
            return (kind, text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        guard let userIndex = rows.lastIndex(where: {
            $0.0 == "user_message" && $0.1 == prompt
        }) else { return false }
        let completion = rows[(userIndex + 1)...].last(where: {
            $0.0 == "assistant_message"
        })
        guard completion?.1 == marker else { return false }
        let providerText = rows[userIndex...].map(\.1).joined(separator: "\n").lowercased()
        return ![
            "401", "unauthorized", "refresh_token", "codex produced no message",
            "the native packaged app is connected to python authority",
        ].contains(where: providerText.contains)
    }
}
