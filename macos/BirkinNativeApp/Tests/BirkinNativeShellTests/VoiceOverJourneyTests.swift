import Foundation
import Testing
@testable import BirkinNativeShell

@Suite("VoiceOver accessibility-seam journeys")
struct VoiceOverJourneyTests {
    @Test("J2 research approval exposes ordered labels values traits and actions")
    func researchApproval() throws {
        let nodes = try #require(ShellVoiceOverModel.journey(.j2ResearchApproval))
        #expect(nodes.map(\.id) == [
            "sessions.research", "composer.draft", "composer.send", "approvals.card",
            "approvals.approve", "activity.receipt", "working-memory.landmark",
        ])
        #expect(nodes[3].value == "Risk, category, and summary")
        #expect(nodes.filter { $0.role == .button }.allSatisfy { $0.actions == ["press"] })
        try writeActionLog(nodes, name: "j2-voiceover-seam-action.log")
    }

    @Test("J6 Computer Use consent exposes status binding and explicit decisions")
    func computerUseConsent() throws {
        let nodes = try #require(ShellVoiceOverModel.journey(.j6ComputerUseConsent))
        #expect(nodes.map(\.id) == [
            "computer-use.landmark", "computer-use.approve", "computer-use.reject",
            "activity.receipt",
        ])
        #expect(nodes.first?.role == .landmark)
        #expect(nodes.dropFirst().allSatisfy { $0.actions == ["press"] })
        try writeActionLog(nodes, name: "j6-voiceover-seam-action.log")
    }

    private func writeActionLog(_ nodes: [ShellAccessibilityNode], name: String) throws {
        let lines = nodes.map {
            "focus:\($0.id)|role:\($0.role.rawValue)|label:\($0.label)|value:\($0.value ?? "none")|actions:\($0.actions.joined(separator: ","))"
        }
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let directory = root.appendingPathComponent(".omo/evidence/native-shell/phase12", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data((lines.joined(separator: "\n") + "\n").utf8)
            .write(to: directory.appendingPathComponent(name), options: .atomic)
    }
}
