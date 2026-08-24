import Testing

@testable import BirkinNativeProtocol

@Suite("Owned terminal projection")
struct TerminalProjectionTests {
    @Test("Python vectors reduce terminal output in sequence")
    func reducesTerminalVectors() throws {
        let vectors = try ProjectionVectors.load()
        let store = NativeProjectionStore()
        try store.apply(snapshot: vectors.snapshot)
        for vector in vectors.events {
            try store.apply(event: vector.envelope)
        }

        let terminal = try #require(store.projection?.terminals.first)
        #expect(terminal.terminalID == "terminal-vector")
        #expect(terminal.screen.contains("hello-native"))
        #expect(terminal.outputSequence == 1)
        #expect(terminal.state == "exited")
        #expect(terminal.exitStatus == 0)
    }
}
