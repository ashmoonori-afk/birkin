public struct NativeTerminalProjection: Equatable, Sendable, Identifiable {
    public let terminalID: String
    public var cwd: String
    private var renderer: NativeTerminalRenderer
    public var outputSequence: Int
    public var state: String
    public var exitStatus: Int?
    public var columns: Int
    public var rows: Int
    public var lease: String?
    public var readOnly: Bool

    public var id: String { terminalID }

    public var screen: String {
        get { renderer.screen }
        set {
            let rendered = renderer.screen
            guard !rendered.isEmpty else {
                renderer.append(newValue)
                return
            }
            let overlap = Self.suffixPrefixOverlap(rendered, newValue)
            renderer.append(String(newValue.dropFirst(overlap)))
        }
    }

    public init(
        terminalID: String,
        cwd: String,
        screen: String,
        outputSequence: Int,
        state: String,
        exitStatus: Int?,
        columns: Int,
        rows: Int,
        lease: String?,
        readOnly: Bool
    ) {
        self.terminalID = terminalID
        self.cwd = cwd
        renderer = NativeTerminalRenderer()
        renderer.append(screen)
        self.outputSequence = outputSequence
        self.state = state
        self.exitStatus = exitStatus
        self.columns = columns
        self.rows = rows
        self.lease = lease
        self.readOnly = readOnly
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.terminalID == rhs.terminalID
            && lhs.cwd == rhs.cwd
            && lhs.screen == rhs.screen
            && lhs.outputSequence == rhs.outputSequence
            && lhs.state == rhs.state
            && lhs.exitStatus == rhs.exitStatus
            && lhs.columns == rhs.columns
            && lhs.rows == rhs.rows
            && lhs.lease == rhs.lease
            && lhs.readOnly == rhs.readOnly
    }

    var canonicalJSON: NativeJSONObject {
        [
            "terminal_id": .string(terminalID),
            "cwd": .string(cwd),
            "screen": .string(screen),
            "output_sequence": .int(outputSequence),
            "state": .string(state),
            "exit_status": exitStatus.map(NativeJSONValue.int) ?? .null,
            "columns": .int(columns),
            "rows": .int(rows),
            "lease": lease.map(NativeJSONValue.string) ?? .null,
            "read_only": .bool(readOnly),
        ]
    }

    private static func suffixPrefixOverlap(_ old: String, _ new: String) -> Int {
        let pattern = Array(new)
        guard !pattern.isEmpty else { return 0 }
        var prefix = Array(repeating: 0, count: pattern.count)
        for index in pattern.indices.dropFirst() {
            var length = prefix[index - 1]
            while length > 0, pattern[index] != pattern[length] {
                length = prefix[length - 1]
            }
            if pattern[index] == pattern[length] { length += 1 }
            prefix[index] = length
        }
        var matched = 0
        let oldCharacters = Array(old)
        for (index, character) in oldCharacters.enumerated() {
            while matched > 0, character != pattern[matched] {
                matched = prefix[matched - 1]
            }
            if character == pattern[matched] { matched += 1 }
            if matched == pattern.count, index != oldCharacters.count - 1 {
                matched = prefix[matched - 1]
            }
        }
        return matched
    }
}
