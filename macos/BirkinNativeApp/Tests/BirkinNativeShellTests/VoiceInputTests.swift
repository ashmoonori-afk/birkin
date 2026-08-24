import Foundation
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Python-gated voice composer input")
@MainActor
struct VoiceInputTests {
    @Test("control is absent unless Python advertises healthy voice input")
    func capabilityGate() {
        let unavailable = session(voiceInputAvailable: false)
        let available = session(voiceInputAvailable: true)
        #expect(!VoiceInputModel.isControlVisible(session: unavailable))
        #expect(VoiceInputModel.isControlVisible(session: available))
    }

    @Test("transcript remains editable draft and never auto-sends")
    func transcriptDoesNotSend() {
        let voice = VoiceInputModel()
        let composer = ConversationComposerModel(draft: "Existing")
        var submitted = 0
        voice.begin(session: session(voiceInputAvailable: true))
        let accepted = voice.applyTranscript(
            "dictated 한국어",
            session: session(voiceInputAvailable: true),
            composer: composer,
            submit: { submitted += 1 }
        )

        #expect(accepted)
        #expect(composer.draft == "Existing dictated 한국어")
        #expect(submitted == 0)
        #expect(!voice.isListening)
    }

    @Test("unadvertised transcript is ignored")
    func transcriptRefused() {
        let voice = VoiceInputModel()
        let composer = ConversationComposerModel(draft: "Keep")
        var submitted = 0
        let accepted = voice.applyTranscript(
            "must not land", session: session(voiceInputAvailable: false),
            composer: composer, submit: { submitted += 1 }
        )
        #expect(!accepted)
        #expect(composer.draft == "Keep")
        #expect(submitted == 0)
    }

    private func session(voiceInputAvailable: Bool) -> NativeReadySession {
        NativeReadySession(
            instanceID: "instance-1", serverVersion: "1.0",
            sessionCapability: "token",
            capabilityExpiresAt: Date(timeIntervalSince1970: 2_000),
            capabilityHardExpiresAt: Date(timeIntervalSince1970: 3_000),
            supportedCommands: ["chat.send"],
            voiceInputAvailable: voiceInputAvailable
        )
    }
}
