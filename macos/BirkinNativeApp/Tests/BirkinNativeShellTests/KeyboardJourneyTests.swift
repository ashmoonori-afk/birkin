import Foundation
import Testing
@testable import BirkinNativeShell

@Suite("Keyboard-only native journeys")
struct KeyboardJourneyTests {
    @Test("J1 first answer is complete without pointer input")
    func firstAnswer() throws {
        let log = ShellKeyboardModel.journey(.j1FirstAnswer)
        #expect(log == [
            "focus:sessions.new", "key:cmd+n", "focus:composer.draft",
            "edit:composer.draft", "key:cmd+return", "focus:conversation.stream",
            "observe:stream-complete", "focus:activity.receipt", "press:activity.receipt",
        ])
        try writeActionLog(log, name: "j1-keyboard-action.log")
    }

    @Test("J3 terminal and file change is complete without pointer input")
    func terminalAndFileChange() throws {
        let log = ShellKeyboardModel.journey(.j3TerminalAndFileChange)
        #expect(log == [
            "focus:terminal.new", "press:terminal.new", "focus:terminal.input",
            "edit:terminal.input", "press:terminal.run", "focus:terminal.output",
            "observe:terminal-output", "key:cmd+shift+a", "focus:approvals.approve",
            "press:approvals.approve", "observe:file-diff", "focus:activity.receipt",
            "press:activity.receipt",
        ])
        try writeActionLog(log, name: "j3-keyboard-action.log")
    }

    @Test("focus order and global key commands cover journey controls")
    func commandAndFocusCoverage() {
        let inventoryIDs = Set(ShellAccessibilityInventory.nodes.map(\.id))
        #expect(ShellKeyboardModel.focusOrder.allSatisfy(inventoryIDs.contains))
        #expect(Set(ShellKeyboardModel.commands.map(\.shortcut)) == [
            "cmd+n", "cmd+return", "cmd+.", "cmd+shift+a", "escape",
            "cmd+1", "cmd+2", "cmd+3",
        ])
        #expect(Set(ShellKeyboardModel.commands.map(\.action)).count == ShellKeyboardModel.commands.count)
    }

    private func writeActionLog(_ values: [String], name: String) throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data((values.joined(separator: "\n") + "\n").utf8)
            .write(to: directory.appendingPathComponent(name), options: .atomic)
    }
}
