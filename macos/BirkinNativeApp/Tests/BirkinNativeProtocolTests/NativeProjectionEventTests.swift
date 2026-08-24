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
        #expect(first.latestAppliedCursor == vectors.events.last?.cursor)
    }

    @Test("answered approvals reconcile into one resolved canonical card")
    func answeredApprovalReconciles() throws {
        let store = NativeProjectionStore()
        try store.apply(snapshot: approvalSnapshot())
        try store.apply(event: approvalEvent(
            cursor: 1,
            type: "approval.requested",
            payload: [
                "approval_id": .string("approval-1"),
                "summary": .string("Run release command"),
                "description": .string("Execute one sealed command"),
                "category": .string("shell"),
                "risk": .string("high"),
                "sealed": .bool(true),
            ]
        ))
        try store.apply(event: approvalEvent(
            cursor: 2,
            type: "approval.answered",
            payload: [
                "approval_id": .string("approval-1"),
                "decision": .string("approve"),
                "outcome": .string("approved"),
                "receipt": .string("exit 0: approved"),
            ]
        ))

        let approvals = try #require(
            store.projection?.panels.first { $0.key == "approvals" }?.items
        )
        let item = try #require(approvals.first)
        #expect(approvals.count == 1)
        #expect(item["summary"] == .string("Run release command"))
        #expect(item["description"] == .string("Execute one sealed command"))
        #expect(item["category"] == .string("shell"))
        #expect(item["risk"] == .string("high"))
        #expect(item["sealed"] == .bool(true))
        #expect(item["decided"] == .bool(true))
        #expect(item["status"] == .string("approved"))
        #expect(item["ui_state"] == .string("succeeded"))
        #expect(item["receipt_ref"] == .string("exit 0: approved"))
        #expect(item["cursor"] == .int(2))
    }

    private func approvalSnapshot() -> NativeEnvelope {
        NativeEnvelope(kind: .snapshot, id: "approval-snapshot", body: [
            "protocol_version": .int(1),
            "session_id": .string("session-1"),
            "cursor": .int(0),
            "panels": .array([
                .object(["key": .string("approvals"), "items": .array([])]),
            ]),
            "conversation": .array([]),
            "composer": .object([
                "can_send": .bool(true),
                "can_interrupt": .bool(false),
                "can_resume": .bool(false),
            ]),
            "status": .object(["connection": .string("connected")]),
            "working_memory": .object([
                "revision": .int(0),
                "goal": .null,
                "fields": .object([
                    "corrections": .array([]),
                    "constraints": .array([]),
                    "decisions": .array([]),
                    "incomplete": .array([]),
                    "evidence": .array([]),
                    "next_actions": .array([]),
                ]),
                "files_evidence": .array([]),
            ]),
            "approval_policy": .object([:]),
            "terminals": .array([]),
            "instance_id": .string("instance-1"),
            "reset_reason": .string("initial"),
        ])
    }

    private func approvalEvent(
        cursor: Int,
        type: String,
        payload: NativeJSONObject
    ) -> NativeEnvelope {
        NativeEnvelope(kind: .event, id: "event-\(cursor)", body: [
            "protocol_version": .int(1),
            "session_id": .string("session-1"),
            "cursor": .int(cursor),
            "event_id": .string("event-\(cursor)"),
            "type": .string(type),
            "timestamp": .string("2026-08-22T00:00:00Z"),
            "actor_id": .string("native-test"),
            "command_id": .string("command-\(cursor)"),
            "payload": .object(payload),
        ])
    }
}
