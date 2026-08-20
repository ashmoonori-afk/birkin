import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Working Memory surface")
struct WorkingMemoryTests {
    @Test("canonical projection maps exactly five labeled rows")
    func fiveRows() {
        let projection = NativeWorkingMemoryProjection(
            revision: 7,
            goal: NativeWorkingMemoryGoal(
                slug: "ship-native", objective: "Ship native", tokensUsed: 12, status: "active"
            ),
            fields: [
                "corrections": ["Corrected"],
                "constraints": ["Offline"],
                "decisions": ["Use Python"],
                "incomplete": ["Render UI"],
                "evidence": ["Tests are red"],
                "next_actions": ["Run green"],
            ],
            filesEvidence: [["summary": .string("workspace/main.py")]]
        )

        let rows = WorkingMemoryPresentation(projection: projection).rows

        #expect(rows.map(\.label) == ["Goals", "Context", "Files", "Constraints", "Notes"])
        #expect(rows[0].values == ["Ship native"])
        #expect(rows[1].values == ["Corrected", "Use Python", "Tests are red"])
        #expect(rows[2].values == ["workspace/main.py"])
        #expect(rows[3].values == ["Offline"])
        #expect(rows[4].values == ["Render UI", "Run green"])
        #expect(rows.map(\.canonicalFields) == [
            ["GoalState.objective"],
            ["corrections", "decisions", "evidence"],
            ["files_evidence"],
            ["constraints"],
            ["incomplete", "next_actions"],
        ])
    }
}
