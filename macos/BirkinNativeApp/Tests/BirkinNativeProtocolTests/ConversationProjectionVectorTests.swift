import Testing

@testable import BirkinNativeProtocol

@Suite("Python conversation projection vectors")
struct ConversationProjectionVectorTests {
    @Test("assistant deltas render progressively and completion is visible")
    func streamProgressesToCompletion() throws {
        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()
        try store.apply(snapshot: vectors.snapshot)
        var streamedTexts: [String] = []

        for vector in vectors.events {
            try store.apply(event: vector.envelope)
            #expect(store.projection?.canonicalJSON == vector.expectedState)
            if let last = store.projection?.conversation.last,
               case .string(let kind) = last["kind"], kind == "assistant_stream",
               case .string(let text) = last["text"] {
                streamedTexts.append(text)
            }
        }

        #expect(streamedTexts == ["Events ", "Events reduced"])
        #expect(store.projection?.conversation.last?.string("text") == "Events reduced")
        #expect(store.projection?.conversation.last?.string("kind") == "assistant_message")
        #expect(store.projection?.composer.canSend == true)
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
