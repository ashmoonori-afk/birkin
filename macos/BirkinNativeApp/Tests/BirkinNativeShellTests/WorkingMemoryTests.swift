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
    @Test("reusable edit model exposes dirty save, revision conflict, and budget flow")
    func editFlow() {
        let editor = WorkingMemoryDraftModel(
            projection: projection(revision: 7, constraints: ["Offline"])
        )
        #expect(!editor.isDirty)
        editor.setValues(["Offline", "Python owns policy"], for: "constraints")
        #expect(editor.isDirty)
        #expect(editor.canPreview)
        #expect(editor.requestedFields == ["constraints": ["Offline", "Python owns policy"]])

        editor.receiveCanonicalFailure(
            code: "E_WORKING_MEMORY_REVISION", message: "stale", currentRevision: 8
        )
        #expect(editor.conflict?.currentRevision == 8)
        #expect(!editor.canPreview)
        editor.rebase(on: projection(revision: 8, constraints: ["Changed elsewhere"]))
        #expect(editor.baseRevision == 8)
        #expect(editor.values["constraints"] == ["Offline", "Python owns policy"])
        #expect(editor.canPreview)

        editor.setValues([String(repeating: "x", count: 20_001)], for: "constraints")
        #expect(editor.renderBudget.isExceeded)
        #expect(!editor.canPreview)
    }

    @MainActor
    @Test("clear scope and budget errors have bounded accessible copy")
    func clearAndBudgetAccessibility() throws {
        let clear = WorkingMemoryClearPresentation(sessionID: "session-1")
        #expect(clear.title == "Clear Working Memory for session-1?")
        #expect(clear.explanation.contains("corrections, constraints, decisions, incomplete items, evidence, and next actions"))
        #expect(clear.explanation.contains("does not clear vault memory, workspace files, or audit history"))
        #expect(clear.confirmAccessibilityLabel == "Clear session Working Memory only")

        let model = WorkingMemoryEditorModel(
            authoritative: projection(revision: 7, constraints: ["Offline"])
        )
        let session = NativeReadySession(
            instanceID: "instance-1", serverVersion: "1.0",
            sessionCapability: "token",
            capabilityExpiresAt: Date(timeIntervalSince1970: 2_000),
            capabilityHardExpiresAt: Date(timeIntervalSince1970: 3_000),
            supportedCommands: ["memory.write"]
        )
        var requests: [NativeCommandRequest] = []
        #expect(model.submitClear(
            availability: MutationAvailability(
                state: .ready(session), now: Date(timeIntervalSince1970: 1_000)
            ),
            expectedCursor: 14,
            session: session,
            submit: { requests.append($0) }
        ))
        #expect(requests.first?.payload == [
            "op": .string("clear"), "expected_revision": .int(7),
        ])
        #expect(model.authoritative.revision == 7)
        #expect(model.isAwaitingConfirmation)

        let longMessage = "working memory exceeds 20000 rendered characters "
            + String(repeating: "x", count: 500)
        let error = WorkingMemoryCanonicalErrorPresentation(
            code: "E_WORKING_MEMORY_BUDGET", message: longMessage
        )
        #expect(error.message.count == 300)
        #expect(error.accessibilityLabel.contains("20,000-character render budget"))
        try writeEvidence(
            WorkingMemoryClearConfirmationView(presentation: clear)
                .frame(width: 440, height: 240),
            named: "working-memory-clear-scope.png"
        )
        try writeEvidence(
            WorkingMemoryCanonicalErrorView(presentation: error)
                .frame(width: 560, height: 180),
            named: "working-memory-budget-error.png"
        )
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

    @MainActor
    private func writeEvidence<Content: View>(
        _ view: Content, named name: String
    ) throws {
        let renderer = ImageRenderer(content: view)
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:])
        else {
            throw CocoaError(.fileWriteUnknown)
        }
        let output = evidenceDirectory().appendingPathComponent(name)
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
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
