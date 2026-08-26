import AppKit
import Foundation
import SwiftUI
import Testing
import Vision

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Packaged snapshot evidence content")
struct SnapshotEvidenceContentTests {
    @MainActor
    @Test("critical snapshots visibly contain canonical rows, output, and import chip")
    func criticalContentIsVisibleAndDistinct() throws {
        let root = evidenceRoot()
        try? FileManager.default.removeItem(at: root)
        try FileManager.default.createDirectory(
            at: root, withIntermediateDirectories: true
        )
        let captureView = SnapshotCaptureView()
        let runtime = BirkinApplicationRuntime(
            socketPath: nil,
            windowCapture: testCapture(captureView),
            emit: { _ in }
        )
        let session = readySession()

        try runtime.store.apply(snapshot: snapshot(includeTerminal: false))
        let conversationURL = root.appendingPathComponent("conversation.png")
        #expect(try render(
            runtime,
            session: session,
            captureView: captureView,
            to: conversationURL
        ))

        try runtime.store.apply(snapshot: snapshot(includeTerminal: true))
        let terminalURL = root.appendingPathComponent("terminal.png")
        #expect(try render(
            runtime,
            session: session,
            captureView: captureView,
            to: terminalURL
        ))

        runtime.jailedDrop.applyCanonicalResult([
            "reference": .object([
                "kind": .string("workspace_import"),
                "import_id": .string("visible-import"),
                "display_name": .string("IMPORT CHIP VISIBLE.txt"),
                "jail_name": .string("visible-import.txt"),
                "sha256": .string(String(repeating: "a", count: 64)),
                "byte_count": .int(42),
            ]),
            "receipt": .object(["copied": .bool(true)]),
        ])
        let importURL = root.appendingPathComponent("import.png")
        #expect(try render(
            runtime,
            session: session,
            captureView: captureView,
            to: importURL
        ))

        let urls = [conversationURL, terminalURL, importURL]
        let images = try urls.map { try Data(contentsOf: $0) }
        #expect(Set(images).count == urls.count)
        for (url, image) in zip(urls, images) {
            #expect(image.count > 10_000, "\(url.lastPathComponent) was too small")
            #expect(try contentColourCount(url) >= 8)
        }

        let conversationText = try recognizedText(conversationURL)
        #expect(conversationText.contains("USER ROW VISIBLE"), "OCR: \(conversationText)")
        #expect(conversationText.contains("ASSISTANT ROW VISIBLE"), "OCR: \(conversationText)")
        let terminalText = try recognizedText(terminalURL)
        #expect(terminalText.contains("TERMINAL OUTPUT VISIBLE"), "OCR: \(terminalText)")
        let terminalLines = try recognizedLines(terminalURL)
        let terminalHeading = try #require(terminalLines.first {
            $0.text.contains("OWNED TERMINAL")
        })
        #expect(
            terminalHeading.bounds.minY >= 0.15,
            "Owned Terminal is visibly sliced at normalized y=\(terminalHeading.bounds.minY)"
        )
        let memoryHeading = try #require(terminalLines.first {
            $0.text.contains("WORKING MEMORY")
        })
        #expect(
            memoryHeading.bounds.minY >= 0.15,
            "Working Memory is visibly sliced at normalized y=\(memoryHeading.bounds.minY)"
        )
        let navigationHeading = try #require(terminalLines
            .filter { $0.text == "NAVIGATION" }
            .max { $0.bounds.maxY < $1.bounds.maxY })
        let conversationHeading = try #require(terminalLines
            .filter { $0.text == "CONVERSATION" }
            .max { $0.bounds.maxY < $1.bounds.maxY })
        let contextHeading = try #require(terminalLines
            .filter { $0.text == "CONTEXT" }
            .max { $0.bounds.maxY < $1.bounds.maxY })
        #expect(navigationHeading.bounds.minX < 0.15)
        #expect(conversationHeading.bounds.minX > 0.18)
        #expect(conversationHeading.bounds.minX < 0.60)
        #expect(contextHeading.bounds.minX > 0.70)
        let headingYs = [
            navigationHeading.bounds.maxY,
            conversationHeading.bounds.maxY,
            contextHeading.bounds.maxY,
        ]
        #expect(
            (headingYs.max() ?? 0) - (headingYs.min() ?? 0) <= 0.02,
            "Column heading top origins must remain aligned: \(headingYs)"
        )
        let importText = try recognizedText(importURL)
        #expect(importText.contains("IMPORT CHIP VISIBLE"), "OCR: \(importText)")
        let recognizedSpecimens = Set(try recognizedCJK(importURL))
        let expectedSpecimens = Set(PackagedWindowCapture.cjkSpecimens)
        #expect(
            recognizedSpecimens == expectedSpecimens,
            "CJK OCR: \(recognizedSpecimens); expected: \(expectedSpecimens)"
        )
        let noCJKURL = root.appendingPathComponent("import-no-cjk.png")
        #expect(try render(
            runtime,
            session: session,
            captureView: captureView,
            to: noCJKURL,
            evidenceSpecimens: []
        ))
        #expect(try topRegionPixelDifference(importURL, noCJKURL) > 500)
    }

    @MainActor
    private func testCapture(_ captureView: SnapshotCaptureView) -> PackagedWindowCapture {
        PackagedWindowCapture(
            preflight: { true },
            windowIDs: { [1] },
            metadata: { _ in .valid },
            image: { _ in
                guard let view = captureView.view else { return nil }
                let representation = view.bitmapImageRepForCachingDisplay(in: view.bounds)
                guard let representation else { return nil }
                view.cacheDisplay(in: view.bounds, to: representation)
                return representation.cgImage
            }
        )
    }

    @MainActor
    private func render(
        _ runtime: BirkinApplicationRuntime,
        session: NativeReadySession,
        captureView: SnapshotCaptureView,
        to url: URL,
        evidenceSpecimens: [String] = PackagedWindowCapture.cjkSpecimens
    ) throws -> Bool {
        let hostingView = NSHostingView(rootView: NativeShellView(
            store: runtime.store,
            connectionState: .ready(session),
            evidenceSpecimens: evidenceSpecimens,
            jailedDrop: runtime.jailedDrop,
            presentationModel: runtime.presentationModel
        ))
        hostingView.frame = NSRect(x: 0, y: 0, width: 1_280, height: 800)
        hostingView.layoutSubtreeIfNeeded()
        captureView.view = hostingView
        return try runtime.renderEvidence(to: url, session: session)
    }

    @MainActor
    private final class SnapshotCaptureView {
        var view: NSView?
    }

    private func readySession() -> NativeReadySession {
        let now = Date()
        return NativeReadySession(
            instanceID: "snapshot-instance", serverVersion: BirkinVersion.packageVersion,
            currentSessionID: "snapshot-session", sessionCapability: "snapshot-capability",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120),
            supportedCommands: ["chat.send", "file.import", "terminal.create"]
        )
    }

    private func snapshot(includeTerminal: Bool) -> NativeEnvelope {
        let terminal: NativeJSONValue = includeTerminal ? .array([.object([
            "terminal_id": .string("terminal-visible"),
            "cwd": .string("/private/workspace"),
            "screen": .string("$ printf evidence\nTERMINAL OUTPUT VISIBLE\n"),
            "output_sequence": .int(1), "state": .string("running"),
            "exit_status": .null, "columns": .int(80), "rows": .int(24),
            "lease": .string("lease-visible"), "read_only": .bool(false),
        ])]) : .array([])
        return NativeEnvelope(kind: .snapshot, id: "snapshot-evidence", body: [
            "protocol_version": .int(1), "session_id": .string("snapshot-session"),
            "cursor": .int(includeTerminal ? 2 : 1),
            "panels": .array([
                .object(["key": .string("sessions_history"), "items": .array([])]),
                .object(["key": .string("approvals"), "items": .array([])]),
                .object(["key": .string("activity_logs"), "items": .array([])]),
            ]),
            "conversation": .array([
                .object([
                    "id": .string("visible-user"), "kind": .string("user_message"),
                    "text": .string("USER ROW VISIBLE"),
                ]),
                .object([
                    "id": .string("visible-assistant"),
                    "kind": .string("assistant_message"),
                    "text": .string("ASSISTANT ROW VISIBLE"),
                ]),
            ]),
            "composer": .object([
                "can_send": .bool(true), "can_interrupt": .bool(false),
                "can_resume": .bool(false),
            ]),
            "status": .object(["connection": .string("connected")]),
            "working_memory": .object([
                "revision": .int(0), "goal": .null,
                "fields": .object([
                    "corrections": .array([]), "constraints": .array([]),
                    "decisions": .array([]), "incomplete": .array([]),
                    "evidence": .array([]), "next_actions": .array([]),
                ]),
                "files_evidence": .array([]),
            ]),
            "approval_policy": .object([:]), "terminals": terminal,
            "instance_id": .string("snapshot-instance"),
            "reset_reason": .string("initial"),
        ])
    }

    private func evidenceRoot() -> URL {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        return root.appendingPathComponent(
            ".omo/evidence/native-shell/snapshot-content", isDirectory: true
        )
    }

    private func recognizedText(_ url: URL) throws -> String {
        try recognizedLines(url)
            .map(\.text)
            .joined(separator: "\n")
    }

    @MainActor
    private func recognizedCJK(_ url: URL) throws -> [String] {
        let data = try Data(contentsOf: url)
        let bitmap = try #require(NSBitmapImageRep(data: data))
        return PackagedWindowCapture.recognizedCJKMarkers(
            try #require(bitmap.cgImage)
        )
    }

    private struct RecognizedLine {
        let text: String
        let bounds: CGRect
    }

    private func recognizedLines(_ url: URL) throws -> [RecognizedLine] {
        let data = try Data(contentsOf: url)
        let bitmap = try #require(NSBitmapImageRep(data: data))
        let image = try #require(bitmap.cgImage)
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["ko-KR", "ja-JP", "en-US"]
        try VNImageRequestHandler(cgImage: image).perform([request])
        return (request.results ?? [])
            .compactMap { observation in
                guard let text = observation.topCandidates(1).first?.string else {
                    return nil
                }
                return RecognizedLine(
                    text: text.uppercased(),
                    bounds: observation.boundingBox
                )
            }
    }

    private func contentColourCount(_ url: URL) throws -> Int {
        let bitmap = try #require(NSBitmapImageRep(data: Data(contentsOf: url)))
        var colours = Set<UInt32>()
        let stepX = max(1, bitmap.pixelsWide / 96)
        let stepY = max(1, bitmap.pixelsHigh / 96)
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: stepX) {
                guard let colour = bitmap.colorAt(x: x, y: y) else { continue }
                let red = UInt32(colour.redComponent * 255)
                let green = UInt32(colour.greenComponent * 255)
                let blue = UInt32(colour.blueComponent * 255)
                colours.insert(red << 16 | green << 8 | blue)
            }
        }
        return colours.count
    }

    private func topRegionPixelDifference(
        _ firstURL: URL,
        _ secondURL: URL
    ) throws -> Int {
        let first = try #require(NSBitmapImageRep(
            data: Data(contentsOf: firstURL)
        ))
        let second = try #require(NSBitmapImageRep(
            data: Data(contentsOf: secondURL)
        ))
        #expect(first.pixelsWide == second.pixelsWide)
        #expect(first.pixelsHigh == second.pixelsHigh)
        let endY = min(160, first.pixelsHigh)
        var differences = 0
        for y in 0..<endY {
            for x in 0..<first.pixelsWide {
                guard let firstColour = first.colorAt(x: x, y: y),
                      let secondColour = second.colorAt(x: x, y: y)
                else { continue }
                let distance =
                    abs(firstColour.redComponent - secondColour.redComponent)
                    + abs(firstColour.greenComponent - secondColour.greenComponent)
                    + abs(firstColour.blueComponent - secondColour.blueComponent)
                if distance > 0.05 { differences += 1 }
            }
        }
        return differences
    }
}
