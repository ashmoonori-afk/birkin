import BirkinNativeProtocol

public enum ShellColumnID: String, CaseIterable, Equatable, Sendable {
    case navigation
    case primary
    case context

    public var title: String {
        switch self {
        case .navigation: "Navigation"
        case .primary: "Conversation"
        case .context: "Context"
        }
    }

    public var accessibilitySortPriority: Double {
        switch self {
        case .navigation: 3
        case .primary: 2
        case .context: 1
        }
    }
}

public enum ShellSectionID: String, CaseIterable, Equatable, Sendable {
    case sessions
    case templates
    case workingMemory
    case conversation
    case composer
    case terminal
    case approvals
    case activity
    case browserAside
    case office
    case computerUse

    public var title: String {
        switch self {
        case .sessions: "Sessions"
        case .templates: "Templates"
        case .workingMemory: "Working Memory"
        case .conversation: "Conversation"
        case .composer: "Composer"
        case .terminal: "Owned Terminal"
        case .approvals: "Approvals"
        case .activity: "Activity"
        case .browserAside: "Browser Aside"
        case .office: "Office"
        case .computerUse: "Computer Use"
        }
    }
}

public enum ShellSectionState: Equatable, Sendable {
    case unavailable(String)
    case empty(String)
    case content(itemCount: Int)
}

public struct ShellSection: Equatable, Sendable {
    public let id: ShellSectionID
    public let state: ShellSectionState
}

public struct ShellColumn: Equatable, Sendable {
    public let id: ShellColumnID
    public let sections: [ShellSection]
}

public struct ShellStructure: Equatable, Sendable {
    public let columns: [ShellColumn]

    public init(store: NativeProjectionStore) {
        let projection = store.projection
        columns = [
            ShellColumn(id: .navigation, sections: [
                Self.panel(.sessions, key: "sessions_history", projection: projection),
                Self.unavailable(.templates, projection: projection),
                Self.workingMemory(projection),
            ]),
            ShellColumn(id: .primary, sections: [
                Self.conversation(projection),
                Self.composer(projection),
                Self.terminal(projection),
            ]),
            ShellColumn(id: .context, sections: [
                Self.panel(.approvals, key: "approvals", projection: projection),
                Self.panel(.activity, key: "activity_logs", projection: projection),
                Self.surface(.browserAside, name: "browser_aside", store: store),
                Self.surface(.office, name: "office", store: store),
                Self.surface(.computerUse, name: "computer_use", store: store),
            ]),
        ]
    }

    private static func panel(
        _ id: ShellSectionID,
        key: String,
        projection: NativeProjectionState?
    ) -> ShellSection {
        guard let projection else { return waiting(id) }
        guard let panel = projection.panels.first(where: { $0.key == key }) else {
            return ShellSection(
                id: id,
                state: .unavailable("Not advertised by the Python projection.")
            )
        }
        return ShellSection(
            id: id,
            state: panel.items.isEmpty
                ? .empty("No \(id.title.lowercased()) yet.")
                : .content(itemCount: panel.items.count)
        )
    }

    private static func workingMemory(
        _ projection: NativeProjectionState?
    ) -> ShellSection {
        guard let projection else { return waiting(.workingMemory) }
        let memory = projection.workingMemory
        let count = memory.fields.values.reduce(0) { $0 + $1.count }
            + memory.filesEvidence.count + (memory.goal == nil ? 0 : 1)
        return ShellSection(
            id: .workingMemory,
            state: count == 0
                ? .empty("No working memory yet.")
                : .content(itemCount: count)
        )
    }

    private static func conversation(_ projection: NativeProjectionState?) -> ShellSection {
        guard let projection else { return waiting(.conversation) }
        return ShellSection(
            id: .conversation,
            state: projection.conversation.isEmpty
                ? .empty("No conversation yet.")
                : .content(itemCount: projection.conversation.count)
        )
    }

    private static func composer(_ projection: NativeProjectionState?) -> ShellSection {
        guard projection != nil else { return waiting(.composer) }
        return ShellSection(id: .composer, state: .empty("Ready for an explicit message."))
    }

    private static func terminal(_ projection: NativeProjectionState?) -> ShellSection {
        guard let projection else { return waiting(.terminal) }
        return ShellSection(
            id: .terminal,
            state: projection.terminals.isEmpty
                ? .empty("No Python terminal yet.")
                : .content(itemCount: projection.terminals.count)
        )
    }

    private static func unavailable(
        _ id: ShellSectionID,
        projection: NativeProjectionState?
    ) -> ShellSection {
        guard projection != nil else { return waiting(id) }
        return ShellSection(
            id: id,
            state: .unavailable("Not advertised by the Python projection.")
        )
    }

    private static func surface(
        _ id: ShellSectionID,
        name: String,
        store: NativeProjectionStore
    ) -> ShellSection {
        guard store.projection != nil else { return waiting(id) }
        guard store.surface(named: name) != nil else {
            return ShellSection(
                id: id,
                state: .unavailable("Not advertised by the Python projection.")
            )
        }
        return ShellSection(id: id, state: .content(itemCount: 1))
    }

    private static func waiting(_ id: ShellSectionID) -> ShellSection {
        ShellSection(id: id, state: .empty("Waiting for the canonical projection."))
    }
}
