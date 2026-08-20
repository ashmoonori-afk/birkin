import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("One-shot session template launcher")
@MainActor
struct TemplateLauncherTests {
    @Test("launching the same one-shot preset twice creates two sessions and never sends")
    func freshSessionPerLaunchAndEditableDraft() {
        let preset = NativeSessionPreset(
            id: "research",
            name: "Research",
            prefill: "Research the following topic:\n",
            persistent: false,
            order: 0
        )
        var identifiers = ["session-research-1", "session-research-2"].makeIterator()
        let launcher = TemplateLauncherModel(
            presets: [preset],
            makeSessionID: { identifiers.next()! }
        )
        var requests: [NativeCommandRequest] = []

        launcher.launch(
            preset,
            expectedCursor: 7,
            sessionCapability: "live-token",
            submit: { requests.append($0) }
        )
        #expect(launcher.draft == preset.prefill)
        #expect(launcher.selectedPresetID == nil)

        launcher.draft += "Swift concurrency cancellation"
        #expect(requests.count == 1)

        launcher.launch(
            preset,
            expectedCursor: 7,
            sessionCapability: "live-token",
            submit: { requests.append($0) }
        )

        #expect(requests.count == 2)
        #expect(requests.map(\.commandType) == ["session.create", "session.create"])
        #expect(requests.compactMap { $0.payload.string("session_id") } == [
            "session-research-1", "session-research-2",
        ])
        #expect(requests.allSatisfy { $0.commandType != "chat.send" })
        #expect(launcher.draft == preset.prefill)
        #expect(launcher.selectedPresetID == nil)
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
