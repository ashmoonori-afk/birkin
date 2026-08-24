import Testing

@testable import BirkinNativeProtocol

@Suite("Canonical projection snapshot reducer")
struct NativeProjectionSnapshotTests {
    @Test("Python snapshot frame becomes typed ephemeral projection state")
    func reducesPythonSnapshot() throws {
        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()

        try store.apply(snapshot: vectors.snapshot)

        #expect(store.latestAppliedCursor == 2)
        #expect(store.projection?.canonicalJSON == vectors.snapshotExpectedState)
    }
}
