import Foundation
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Conversation controls")
@MainActor
struct ConversationControlsTests {
    @Test("composer sends chat.send only through live mutation authority")
    func composerRoutesSend() {
        let session = readySession(commands: ["chat.send"])
        let availability = MutationAvailability(
            state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
        )
        let composer = ConversationComposerModel(draft: "Ship Wave 6.3")
        var requests: [NativeCommandRequest] = []

        let sent = composer.send(
            availability: availability,
            canSend: true,
            expectedCursor: 12,
            session: session,
            submit: { requests.append($0) }
        )

        #expect(sent)
        #expect(requests.count == 1)
        #expect(requests[0].commandType == "chat.send")
        #expect(requests[0].expectedCursor == 12)
        #expect(requests[0].payload.string("text") == "Ship Wave 6.3")
        #expect(composer.draft.isEmpty)
    }

    @Test("typed attachments persist on refusal and clear after accepted send")
    func attachmentLifecycle() throws {
        let session = readySession(commands: ["chat.send"])
        let composer = ConversationComposerModel(draft: "Inspect this")
        let attachment = try #require(ImportedReference(.object([
            "kind": .string("workspace_import"),
            "import_id": .string("import-1"),
            "display_name": .string("plan.txt"),
            "jail_name": .string("import-1.txt"),
            "sha256": .string(String(repeating: "a", count: 64)),
            "byte_count": .int(42),
        ])))
        composer.attach(attachment)

        #expect(!composer.send(
            availability: MutationAvailability(state: .disconnected), canSend: true,
            expectedCursor: 1, session: session, submit: { _ in }
        ))
        #expect(composer.attachments == [attachment])

        var request: NativeCommandRequest?
        #expect(composer.send(
            availability: MutationAvailability(
                state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
            ), canSend: true, expectedCursor: 2, session: session,
            submit: { request = $0 }
        ))
        #expect(request?.payload.array("attachments")?.count == 1)
        #expect(composer.attachments.isEmpty)
    }

    @Test("typed conversation rows include lifecycle and canonical failures")
    func typedRows() {
        let rows = ConversationRows.parse(
            conversation: [
                ["id": .string("user"), "kind": .string("user_message"), "text": .string("go")],
                ["id": .string("stream"), "kind": .string("assistant_stream"), "text": .string("working")],
            ],
            approvals: [
                ["id": .string("approval"), "kind": .string("approval"), "summary": .string("Run tool"), "ui_state": .string("action_needed")],
                ["id": .string("question"), "kind": .string("question"), "summary": .string("Which target?"), "ui_state": .string("action_needed")],
            ],
            activity: [
                ["id": .string("tool"), "kind": .string("activity"), "summary": .string("grep"), "ui_state": .string("running"), "status": .string("started")],
                ["id": .string("receipt"), "kind": .string("receipt"), "summary": .string("Done"), "ui_state": .string("succeeded")],
                ["id": .string("failure"), "kind": .string("failure"), "summary": .string("Provider failed"), "ui_state": .string("failed"), "code": .string("E_PROVIDER")],
                ["id": .string("interrupted"), "kind": .string("interrupted"), "summary": .string("Interrupted"), "ui_state": .string("paused")],
            ]
        )
        #expect(rows.map(\.kind) == [.user, .assistant, .approval, .question, .tool, .receipt, .failure, .interrupted])
        #expect(rows[1].state == .streaming)
        #expect(rows[6].failure?.code == "E_PROVIDER")
    }

    @Test("turn command factories follow canonical enabled-state matrix")
    func turnControlMatrix() throws {
        let commands: Set<String> = ["chat.steer", "chat.interrupt", "chat.resume", "chat.retry"]
        let session = readySession(commands: commands)
        let ready = MutationAvailability(
            state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
        )
        let idle = ConversationTurnState(canSend: true, canInterrupt: false, canResume: false, hasFailedIntent: false)
        let active = ConversationTurnState(canSend: false, canInterrupt: true, canResume: false, hasFailedIntent: false)
        let stopped = ConversationTurnState(canSend: true, canInterrupt: false, canResume: true, hasFailedIntent: true)
        #expect(ConversationCommandFactory.availability(for: .steer("redirect"), turn: active, mutation: ready, session: session).isEnabled)
        #expect(ConversationCommandFactory.availability(for: .interrupt, turn: active, mutation: ready, session: session).isEnabled)
        #expect(ConversationCommandFactory.availability(for: .resume, turn: stopped, mutation: ready, session: session).isEnabled)
        #expect(ConversationCommandFactory.availability(for: .retry, turn: stopped, mutation: ready, session: session).isEnabled)
        #expect(!ConversationCommandFactory.availability(for: .interrupt, turn: idle, mutation: ready, session: session).isEnabled)
        let request = try ConversationCommandFactory.request(
            for: .steer(" redirect "), expectedCursor: 9, session: session
        )
        #expect(request.commandType == "chat.steer")
        #expect(request.payload.string("text") == "redirect")
    }

    @Test("oversized code-mode payload is blocked before transport")
    func oversizedCodePayloadIsBlocked() {
        let session = readySession(commands: ["chat.send"])
        let availability = MutationAvailability(
            state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
        )
        let composer = ConversationComposerModel(draft: String(repeating: "x", count: 65_526))
        composer.isCodeMode = true
        var requests: [NativeCommandRequest] = []

        let sent = composer.send(
            availability: availability,
            canSend: true,
            expectedCursor: 12,
            session: session,
            submit: { requests.append($0) }
        )

        #expect(!sent)
        #expect(requests.isEmpty)
        #expect(composer.draftByteCount == 65_537)
        #expect(composer.visibleReason == "Payload is 65537 bytes; the limit is 65536 bytes.")
        #expect((composer.visibleReason?.count ?? 0) < 100)
    }

    @Test("Korean marked text suppresses Cmd-Return until composition commits")
    func koreanIMEGuard() {
        #expect(!SendKeyPolicy.shouldSend(
            commandPressed: true, returnPressed: true, hasMarkedText: true
        ))
        #expect(SendKeyPolicy.shouldSend(
            commandPressed: true, returnPressed: true, hasMarkedText: false
        ))
        #expect(!SendKeyPolicy.shouldSend(
            commandPressed: false, returnPressed: true, hasMarkedText: false
        ))
    }

    @Test("disconnected composer does not send")
    func composerHonorsMutationGate() {
        let session = readySession(commands: ["chat.send"])
        let composer = ConversationComposerModel(draft: "Do not send")
        var requests: [NativeCommandRequest] = []

        let sent = composer.send(
            availability: MutationAvailability(state: .disconnected),
            canSend: true,
            expectedCursor: 0,
            session: session,
            submit: { requests.append($0) }
        )

        #expect(!sent)
        #expect(requests.isEmpty)
        #expect(composer.visibleReason == "Disconnected from the Python authority.")
    }

    private func readySession(commands: Set<String>) -> NativeReadySession {
        NativeReadySession(
            instanceID: "instance-1",
            serverVersion: "1.0",
            sessionCapability: "live-token",
            capabilityExpiresAt: Date(timeIntervalSince1970: 2_000),
            capabilityHardExpiresAt: Date(timeIntervalSince1970: 3_000),
            supportedCommands: commands
        )
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func array(_ key: String) -> [NativeJSONValue]? {
        guard case .array(let value) = self[key] else { return nil }
        return value
    }
}
