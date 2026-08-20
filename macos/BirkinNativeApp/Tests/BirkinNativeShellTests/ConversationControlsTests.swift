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
}
