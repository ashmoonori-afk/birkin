import BirkinNativeProtocol
import SwiftUI

@MainActor
public final class VoiceInputModel: ObservableObject {
    @Published public private(set) var isListening = false

    public init() {}

    public static func isControlVisible(session: NativeReadySession?) -> Bool {
        session?.voiceInputAvailable == true
    }

    public func begin(session: NativeReadySession) {
        isListening = session.voiceInputAvailable
    }

    public func cancel() {
        isListening = false
    }

    /// Applies Python-advertised transcription as draft text only. The submit
    /// closure is deliberately accepted but never called, making no-auto-send
    /// part of this boundary's executable contract.
    @discardableResult
    public func applyTranscript(
        _ transcript: String,
        session: NativeReadySession,
        composer: ConversationComposerModel,
        submit _: () -> Void
    ) -> Bool {
        guard session.voiceInputAvailable else {
            isListening = false
            return false
        }
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            isListening = false
            return false
        }
        composer.draft += composer.draft.isEmpty ? text : " \(text)"
        isListening = false
        return true
    }
}

public struct VoiceInputControl: View {
    @ObservedObject private var model: VoiceInputModel
    private let session: NativeReadySession
    private let beginCapture: () -> Void

    public init(
        model: VoiceInputModel,
        session: NativeReadySession,
        beginCapture: @escaping () -> Void
    ) {
        self.model = model
        self.session = session
        self.beginCapture = beginCapture
    }

    public var body: some View {
        if VoiceInputModel.isControlVisible(session: session) {
            Button {
                model.begin(session: session)
                beginCapture()
            } label: {
                Label(
                    model.isListening ? "Listening" : "Push to talk",
                    systemImage: model.isListening ? "waveform" : "mic"
                )
            }
            .accessibilityHint("Transcription is inserted into the editable draft and is not sent")
        }
    }
}
