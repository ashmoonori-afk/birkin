import Testing

@testable import BirkinNativeProtocol

@Suite("Canonical projection cursor gaps")
struct NativeProjectionGapTests {
    @Test("a skipped cursor discards state instead of patching the gap event")
    func gapDiscardsProjection() throws {
        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()
        try store.apply(snapshot: vectors.snapshot)
        for vector in vectors.events {
            try store.apply(event: vector.envelope)
        }

        try store.apply(event: vectors.gapEvent)

        #expect(store.projection == nil)
        #expect(store.latestAppliedCursor == nil)
        #expect(store.status == .replayRequired(NativeReplayRequest(
            afterCursor: 0,
            knownInstanceID: nil,
            replay: true
        )))
    }
}
