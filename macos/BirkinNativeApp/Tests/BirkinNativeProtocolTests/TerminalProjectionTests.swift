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

    @Test("split VT output events preserve canonical bytes and render like one event")
    func splitVTEventsMatchUnsplitRendering() throws {
        let split = NativeProjectionStore()
        try split.apply(snapshot: emptySnapshot(id: "split-snapshot"))
        try split.apply(event: terminalEvent(
            cursor: 1, type: "terminal.opened", payload: [
                "terminal_id": .string("terminal"), "cwd": .string("."),
                "lease": .string("[REDACTED]"),
            ]
        ))
        try split.apply(event: terminalEvent(
            cursor: 2, type: "terminal.output", payload: [
                "terminal_id": .string("terminal"), "sequence": .int(1),
                "data": .string("abc\r\n\u{1B}["),
            ]
        ))
        try split.apply(event: terminalEvent(
            cursor: 3, type: "terminal.output", payload: [
                "terminal_id": .string("terminal"), "sequence": .int(2),
                "data": .string("1A\rOK"),
            ]
        ))

        let unsplit = NativeProjectionStore()
        try unsplit.apply(snapshot: emptySnapshot(id: "unsplit-snapshot"))
        try unsplit.apply(event: terminalEvent(
            cursor: 1, type: "terminal.opened", payload: [
                "terminal_id": .string("terminal"), "cwd": .string("."),
                "lease": .string("[REDACTED]"),
            ]
        ))
        try unsplit.apply(event: terminalEvent(
            cursor: 2, type: "terminal.output", payload: [
                "terminal_id": .string("terminal"), "sequence": .int(1),
                "data": .string("abc\r\n\u{1B}[1A\rOK"),
            ]
        ))

        let splitTerminal = try #require(split.projection?.terminals.first)
        let unsplitTerminal = try #require(unsplit.projection?.terminals.first)
        #expect(splitTerminal.screen == "OKc")
        #expect(splitTerminal.screen == unsplitTerminal.screen)
        #expect(splitTerminal.canonicalJSON["screen"] == .string("abc\r\n\u{1B}[1A\rOK"))
        #expect(splitTerminal.canonicalJSON["screen"] == unsplitTerminal.canonicalJSON["screen"])
    }

    private func emptySnapshot(id: String) -> NativeEnvelope {
        NativeEnvelope(kind: .snapshot, id: id, body: [
            "protocol_version": .int(1), "session_id": .string("session-1"),
            "cursor": .int(0), "panels": .array([]), "conversation": .array([]),
            "composer": .object([
                "can_send": .bool(true), "can_interrupt": .bool(false),
                "can_resume": .bool(false),
            ]),
            "status": .object(["connection": .string("connected")]),
            "working_memory": .object([
                "revision": .int(0), "goal": .null,
                "fields": .object([
                    "corrections": .array([]), "constraints": .array([]),
                    "decisions": .array([]), "incomplete": .array([]),
                    "evidence": .array([]), "next_actions": .array([]),
                ]),
                "files_evidence": .array([]),
            ]),
            "approval_policy": .object([:]), "terminals": .array([]),
            "instance_id": .string("instance-1"), "reset_reason": .string("initial"),
        ])
    }

    private func terminalEvent(
        cursor: Int,
        type: String,
        payload: NativeJSONObject
    ) -> NativeEnvelope {
        NativeEnvelope(kind: .event, id: "event-\(cursor)", body: [
            "protocol_version": .int(1), "session_id": .string("session-1"),
            "cursor": .int(cursor), "event_id": .string("event-\(cursor)"),
            "type": .string(type), "timestamp": .string("2026-09-04T00:00:00Z"),
            "actor_id": .string("native-test"), "command_id": .string("command-\(cursor)"),
            "payload": .object(payload),
        ])
    }
}
