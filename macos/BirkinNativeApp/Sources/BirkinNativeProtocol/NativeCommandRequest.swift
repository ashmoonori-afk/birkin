public struct NativeCommandRequest: Equatable, Sendable {
    public let frameID: String
    public let commandID: String
    public let expectedCursor: Int
    public let commandType: String
    public let payload: NativeJSONObject
    public let sessionCapability: String
    public let viewID: String

    public init(
        frameID: String,
        commandID: String,
        expectedCursor: Int,
        commandType: String,
        payload: NativeJSONObject,
        sessionCapability: String,
        viewID: String
    ) {
        self.frameID = frameID
        self.commandID = commandID
        self.expectedCursor = expectedCursor
        self.commandType = commandType
        self.payload = payload
        self.sessionCapability = sessionCapability
        self.viewID = viewID
    }

    public var envelope: NativeEnvelope {
        NativeEnvelope(kind: .command, id: frameID, body: [
            "session_capability": .string(sessionCapability),
            "command": .object([
                "protocol_version": .int(NativeProtocol.version),
                "command_id": .string(commandID),
                "expected_cursor": .int(expectedCursor),
                "type": .string(commandType),
                "payload": .object(payload),
                "client_context": .object([
                    "surface": .string("macos"),
                    "view_id": .string(viewID),
                ]),
            ]),
        ])
    }
}
