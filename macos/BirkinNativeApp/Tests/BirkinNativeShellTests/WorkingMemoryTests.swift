import AppKit
import SwiftUI
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

    @MainActor
    @Test("requested preview stays distinct until canonical confirmation")
    func requestedEffectiveConfirmation() {
        let authoritative = projection(revision: 7, constraints: ["Offline"])
        let model = WorkingMemoryEditorModel(authoritative: authoritative)
        model.receivePreview(
            requested: ["constraints": ["Offline", "Python owns policy"]],
            effective: projection(
                revision: 8, constraints: ["Offline", "Python owns policy"]
            )
        )
        #expect(model.authoritative.revision == 7)
        #expect(model.pending?.requested["constraints"] == [
            "Offline", "Python owns policy",
        ])
        #expect(model.pending?.effective.revision == 8)
        #expect(model.isOptimistic)

        let session = NativeReadySession(
            instanceID: "instance-1", serverVersion: "1.0",
            sessionCapability: "token",
            capabilityExpiresAt: Date(timeIntervalSince1970: 2_000),
            capabilityHardExpiresAt: Date(timeIntervalSince1970: 3_000),
            supportedCommands: ["memory.write"]
        )
        var requests: [NativeCommandRequest] = []
        #expect(model.submit(
            availability: MutationAvailability(
                state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
            ),
            expectedCursor: 12,
            session: session,
            submit: { requests.append($0) }
        ))
        #expect(requests.first?.commandType == "memory.write")
        #expect(model.isAwaitingConfirmation)
        #expect(model.authoritative.revision == 7)

        model.confirm(projection(revision: 8, constraints: ["Offline", "Python owns policy"]))
        #expect(!model.isOptimistic)
        #expect(model.pending == nil)
        #expect(model.authoritative.revision == 8)
    }

    @MainActor
    @Test("five-row Working Memory renders screenshot evidence")
    func screenshotEvidence() throws {
        let projection = NativeWorkingMemoryProjection(
            revision: 7,
            goal: NativeWorkingMemoryGoal(
                slug: "ship-native", objective: "Ship native", tokensUsed: 12, status: "active"
            ),
            fields: [
                "corrections": ["Corrected"], "constraints": ["Offline"],
                "decisions": ["Use Python"], "incomplete": ["Render UI"],
                "evidence": ["Tests are green"], "next_actions": ["Verify"],
            ],
            filesEvidence: [["summary": .string("workspace/main.py")]]
        )
        let view = WorkingMemoryView(
            presentation: WorkingMemoryPresentation(projection: projection)
        )
        .padding()
        .frame(width: 420, height: 620, alignment: .topLeading)
        let renderer = ImageRenderer(content: view)
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:])
        else {
            Issue.record("ImageRenderer did not produce Working Memory PNG")
            return
        }
        let output = evidenceDirectory()
            .appendingPathComponent("working-memory-five-rows.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 10_000)
    }

    private func projection(
        revision: Int, constraints: [String]
    ) -> NativeWorkingMemoryProjection {
        NativeWorkingMemoryProjection(
            revision: revision,
            goal: nil,
            fields: [
                "corrections": [], "constraints": constraints, "decisions": [],
                "incomplete": [], "evidence": [], "next_actions": [],
            ],
            filesEvidence: []
        )
    }

    private func evidenceDirectory() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".omo/evidence/native-shell")
    }
}
