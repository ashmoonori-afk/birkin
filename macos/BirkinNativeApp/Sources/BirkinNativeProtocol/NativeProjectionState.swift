public struct NativeProjectionPanel: Equatable, Sendable {
    public let key: String
    public var items: [NativeJSONObject]
}

public struct NativeProjectionComposer: Equatable, Sendable {
    public var canSend: Bool
    public var canInterrupt: Bool
    public var canResume: Bool
}

public struct NativeProjectionState: Equatable, Sendable {
    public let protocolVersion: Int
    public let sessionID: String
    public var cursor: Int
    public var panels: [NativeProjectionPanel]
    public var conversation: [NativeJSONObject]
    public var composer: NativeProjectionComposer
    public let connection: String

    var canonicalJSON: NativeJSONObject {
        [
            "protocol_version": .int(protocolVersion),
            "session_id": .string(sessionID),
            "cursor": .int(cursor),
            "panels": .array(panels.map { panel in
                .object([
                    "key": .string(panel.key),
                    "items": .array(panel.items.map(NativeJSONValue.object)),
                ])
            }),
            "conversation": .array(conversation.map(NativeJSONValue.object)),
            "composer": .object([
                "can_send": .bool(composer.canSend),
                "can_interrupt": .bool(composer.canInterrupt),
                "can_resume": .bool(composer.canResume),
            ]),
            "status": .object(["connection": .string(connection)]),
        ]
    }
}

public struct NativeProjectionError: Error, Equatable, Sendable, CustomStringConvertible {
    public let reason: String
    public var description: String { reason }

    init(_ reason: String) {
        self.reason = reason
    }
}
