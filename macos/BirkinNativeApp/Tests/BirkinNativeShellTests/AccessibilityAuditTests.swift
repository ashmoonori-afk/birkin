import Testing
@testable import BirkinNativeShell

@Suite("Shell accessibility inventory")
struct AccessibilityAuditTests {
    @Test("every interactive shell control has a unique nonempty label and action")
    func completeControlInventory() {
        let nodes = ShellAccessibilityInventory.nodes
        #expect(Set(nodes.map(\.id)).count == nodes.count)
        #expect(nodes.allSatisfy { !$0.surface.trimmingCharacters(in: .whitespaces).isEmpty })
        #expect(nodes.allSatisfy { !$0.label.trimmingCharacters(in: .whitespaces).isEmpty })
        #expect(nodes.filter { $0.role != .landmark && $0.role != .status }
            .allSatisfy { !$0.actions.isEmpty })
        #expect(Set(nodes.map(\.label)).count == nodes.count)
    }

    @Test("landmarks cover every visible shell surface")
    func completeLandmarks() {
        let landmarks = Set(ShellAccessibilityInventory.nodes
            .filter { $0.role == .landmark }.map(\.surface))
        #expect(landmarks == [
            "navigation", "sessions", "working-memory", "primary", "conversation",
            "terminal", "context", "approvals", "activity", "browser",
            "computer-use", "office",
        ])
    }
}
