import BirkinNativeProtocol
import Combine
import Foundation

@MainActor
public final class TemplateLauncherModel: ObservableObject {
    public let presets: [NativeSessionPreset]
    @Published public var draft: String
    @Published public private(set) var selectedPresetID: String?

    private let makeSessionID: () -> String

    public init(
        presets: [NativeSessionPreset],
        draft: String = "",
        makeSessionID: @escaping () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.presets = presets.sorted { $0.order < $1.order }
        self.draft = draft
        self.selectedPresetID = nil
        self.makeSessionID = makeSessionID
    }

    public func launch(
        _ preset: NativeSessionPreset,
        expectedCursor: Int,
        sessionCapability: String,
        submit: (NativeCommandRequest) -> Void
    ) {
        selectedPresetID = preset.id
        let sessionID = makeSessionID()
        let commandID = "template-\(sessionID)"
        submit(NativeCommandRequest(
            frameID: commandID,
            commandID: commandID,
            expectedCursor: expectedCursor,
            commandType: "session.create",
            payload: ["session_id": .string(sessionID)],
            sessionCapability: sessionCapability,
            viewID: "window-main"
        ))
        draft = preset.prefill
        if !preset.persistent {
            selectedPresetID = nil
        }
    }
}
