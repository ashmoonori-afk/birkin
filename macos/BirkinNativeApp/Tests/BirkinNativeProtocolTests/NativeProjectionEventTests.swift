import Testing

@testable import BirkinNativeProtocol

@Suite("Canonical projection event reducer")
struct NativeProjectionEventTests {
    @Test("increasing Python event cursors reduce on top of the snapshot")
    func reducesOrderedEvents() throws {
        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()
        try store.apply(snapshot: vectors.snapshot)

        for vector in vectors.events {
            try store.apply(event: vector.envelope)
            #expect(store.latestAppliedCursor == vector.cursor)
            #expect(store.projection?.canonicalJSON == vector.expectedState)
        }
    }

    @Test("the same ordered sequence always produces the same projection")
    func orderedReductionIsDeterministic() throws {
        let vectors = try ProjectionVectors.load()
        let first = NativeProjectionStore()
        let second = NativeProjectionStore()

        for store in [first, second] {
            try store.apply(snapshot: vectors.snapshot)
            for vector in vectors.events {
                try store.apply(event: vector.envelope)
            }
        }

        #expect(first.projection == second.projection)
        #expect(first.latestAppliedCursor == 9)
    }
}
