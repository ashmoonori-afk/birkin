import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol

@Suite("Packaged provider completion evidence")
struct PackagedProviderCompletionTests {
    @Test("only the exact projected provider completion is accepted")
    func exactCompletion() {
        let valid: [NativeJSONObject] = [
            [
                "id": .string("user"), "kind": .string("user_message"),
                "text": .string(PackagedProviderCompletion.prompt),
            ],
            [
                "id": .string("assistant"), "kind": .string("assistant_message"),
                "text": .string(PackagedProviderCompletion.marker),
            ],
        ]
        #expect(PackagedProviderCompletion.validate(valid))
    }

    @Test("canned and credential-error replies are rejected")
    func rejectsNonProviderEvidence() {
        for reply in [
            "The native packaged app is connected to Python authority.",
            "401 Unauthorized: refresh_token_reused",
            "[birkin] Codex produced no message.",
        ] {
            let rows: [NativeJSONObject] = [
                [
                    "id": .string("user"), "kind": .string("user_message"),
                    "text": .string(PackagedProviderCompletion.prompt),
                ],
                [
                    "id": .string("assistant"), "kind": .string("assistant_message"),
                    "text": .string(reply),
                ],
            ]
            #expect(!PackagedProviderCompletion.validate(rows))
        }
    }
}
