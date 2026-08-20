import Foundation

public enum ShellAccessibilityRole: String, Equatable, Sendable {
    case landmark
    case button
    case toggle
    case textField
    case textArea
    case status
    case adjustable
}

public struct ShellAccessibilityNode: Equatable, Identifiable, Sendable {
    public let id: String
    public let surface: String
    public let role: ShellAccessibilityRole
    public let label: String
    public let value: String?
    public let actions: [String]
    public let sortPriority: Int

    public init(
        id: String,
        surface: String,
        role: ShellAccessibilityRole,
        label: String,
        value: String? = nil,
        actions: [String] = [],
        sortPriority: Int
    ) {
        self.id = id
        self.surface = surface
        self.role = role
        self.label = label
        self.value = value
        self.actions = actions
        self.sortPriority = sortPriority
    }
}

public enum ShellAccessibilityInventory {
    public static let nodes: [ShellAccessibilityNode] = [
        node("connection.status", "chrome", .status, "Connection status", value: "Connection state and transport", priority: 1000),
        node("connection.diagnostics", "chrome", .button, "Show connection diagnostics", actions: ["press"], priority: 990),
        node("navigation.column", "navigation", .landmark, "Navigation column", priority: 900),
        node("navigation.sessions", "sessions", .landmark, "Sessions", priority: 890),
        node("sessions.new", "sessions", .button, "New session", actions: ["press"], priority: 880),
        node("sessions.research", "sessions", .button, "Launch Research template", actions: ["press"], priority: 870),
        node("sessions.data", "sessions", .button, "Launch Data Analysis template", actions: ["press"], priority: 860),
        node("sessions.writing", "sessions", .button, "Launch Writing template", actions: ["press"], priority: 850),
        node("sessions.automation", "sessions", .button, "Launch Automation template", actions: ["press"], priority: 840),
        node("working-memory.landmark", "working-memory", .landmark, "Working Memory", priority: 830),
        node("working-memory.clear", "working-memory", .button, "Review session Working Memory clear scope", actions: ["press"], priority: 820),
        node("primary.column", "primary", .landmark, "Primary column", priority: 700),
        node("conversation.stream", "conversation", .landmark, "Conversation message stream", priority: 690),
        node("composer.code-mode", "composer", .toggle, "Code mode", value: "On or off", actions: ["toggle"], priority: 680),
        node("composer.draft", "composer", .textArea, "Message draft", value: "Editable text", actions: ["edit"], priority: 670),
        node("composer.import", "composer", .button, "Import file into workspace jail", actions: ["press", "drop"], priority: 660),
        node("composer.voice", "composer", .button, "Start voice input", actions: ["press"], priority: 650),
        node("composer.send", "composer", .button, "Send message", actions: ["press"], priority: 640),
        node("terminal.landmark", "terminal", .landmark, "Python terminal", priority: 620),
        node("terminal.new", "terminal", .button, "Request new Python terminal", actions: ["press"], priority: 610),
        node("terminal.output", "terminal", .landmark, "Terminal text snapshot", priority: 600),
        node("terminal.input", "terminal", .textField, "Terminal input", value: "Editable text", actions: ["edit"], priority: 590),
        node("terminal.run", "terminal", .button, "Run terminal input", actions: ["press"], priority: 580),
        node("terminal.interrupt", "terminal", .button, "Interrupt Python terminal", actions: ["press"], priority: 570),
        node("terminal.close", "terminal", .button, "Close Python terminal", actions: ["press"], priority: 560),
        node("context.column", "context", .landmark, "Context column", priority: 500),
        node("approvals.landmark", "approvals", .landmark, "Approvals", priority: 490),
        node("approvals.card", "approvals", .landmark, "Pending approval", value: "Risk, category, and summary", priority: 480),
        node("approvals.reject", "approvals", .button, "Reject approval", actions: ["press"], priority: 470),
        node("approvals.approve", "approvals", .button, "Approve request", actions: ["press"], priority: 460),
        node("activity.landmark", "activity", .landmark, "Activity", priority: 450),
        node("activity.hide-read", "activity", .toggle, "Hide read activity", value: "On or off", actions: ["toggle"], priority: 440),
        node("activity.receipt", "activity", .button, "Activity receipt", actions: ["press"], priority: 430),
        node("browser.landmark", "browser", .landmark, "Browser Aside private workspace", priority: 420),
        node("browser.back", "browser", .button, "Browser back", actions: ["press"], priority: 410),
        node("browser.forward", "browser", .button, "Browser forward", actions: ["press"], priority: 400),
        node("browser.reload", "browser", .button, "Reload browser", actions: ["press"], priority: 390),
        node("browser.navigate", "browser", .button, "Navigate browser", actions: ["press"], priority: 380),
        node("computer-use.landmark", "computer-use", .landmark, "Computer Use consent", priority: 370),
        node("computer-use.approve", "computer-use", .button, "Approve Computer Use once", actions: ["press"], priority: 360),
        node("computer-use.reject", "computer-use", .button, "Reject Computer Use", actions: ["press"], priority: 350),
        node("office.landmark", "office", .landmark, "Office document service", priority: 340),
        node("office.new", "office", .button, "Create jailed document", actions: ["press"], priority: 330),
        node("office.open", "office", .button, "Open jailed document", actions: ["press"], priority: 320),
        node("panel.navigation", "adaptive-navigation", .button, "Show Navigation panel", actions: ["press"], priority: 210),
        node("panel.primary", "adaptive-navigation", .button, "Show Primary panel", actions: ["press"], priority: 200),
        node("panel.context", "adaptive-navigation", .button, "Show Context panel", actions: ["press"], priority: 190),
        node("menu.connection", "status-menu", .button, "Open connection details", actions: ["press"], priority: 100),
        node("menu.session", "status-menu", .button, "Open current session", actions: ["press"], priority: 90),
        node("menu.approval", "status-menu", .button, "Open pending approval", actions: ["press"], priority: 80),
    ]

    private static func node(
        _ id: String,
        _ surface: String,
        _ role: ShellAccessibilityRole,
        _ label: String,
        value: String? = nil,
        actions: [String] = [],
        priority: Int
    ) -> ShellAccessibilityNode {
        ShellAccessibilityNode(
            id: id, surface: surface, role: role, label: label,
            value: value, actions: actions, sortPriority: priority
        )
    }
}
