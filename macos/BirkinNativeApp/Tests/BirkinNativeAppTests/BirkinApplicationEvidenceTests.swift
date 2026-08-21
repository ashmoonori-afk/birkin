import AppKit
import Foundation
import Testing

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@Suite("Packaged application visual evidence", .serialized)
struct BirkinApplicationEvidenceTests {
    private static func contentPixelCount(_ url: URL) throws -> Int {
        let data = try Data(contentsOf: url)
        let image = try #require(NSBitmapImageRep(data: data))
        var seen = Set<UInt32>()
        let stepX = max(1, image.pixelsWide / 96)
        let stepY = max(1, image.pixelsHigh / 96)
        for y in stride(from: 0, to: image.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: image.pixelsWide, by: stepX) {
                guard let color = image.colorAt(x: x, y: y) else { continue }
                let red = UInt32(color.redComponent * 255)
                let green = UInt32(color.greenComponent * 255)
                let blue = UInt32(color.blueComponent * 255)
                seen.insert(red << 16 | green << 8 | blue)
            }
        }
        return seen.count
    }

    @MainActor
    @Test("rendered evidence carries real panel content and distinct states")
    func evidenceIsContentfulAndDistinct() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-evidence-\(UUID().uuidString)")
        let harness = try AppHarness.launch(root: root)
        let socketPath = try #require(harness.socketPath)
        let screenshot = root.appendingPathComponent("surface.png")
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            screenshotPath: screenshot.path,
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }
        try await withTimeout("office surface") {
            try await events.wait(for: "surface-rendered name=office")
        }

        #expect(events.contains("surface-rendered name=browser_aside"))
        #expect(events.contains("surface-rendered name=computer_use"))
        #expect(FileManager.default.fileExists(atPath: screenshot.path))
        let firstColours = try Self.contentPixelCount(screenshot)
        #expect(firstColours >= 8, "rendered evidence has \(firstColours) colours")
        let firstBytes = try Data(contentsOf: screenshot)

        let ready = try #require(readySessionForEvidence(runtime))
        runtime.submit(NativeCommandRequest(
            frameID: "evidence-office-frame", commandID: "evidence-office",
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            commandType: "office.create",
            payload: [
                "format": .string("docx"),
                "content": .object(["paragraphs": .array([.string("Evidence body")])]),
                "output_name": .string("evidence.docx"),
            ],
            sessionCapability: ready.sessionCapability, viewID: "office"
        ))
        try await withTimeout("office surface update") {
            try await events.wait(for: "surface-rendered name=office", occurrence: 2)
        }

        let secondBytes = try Data(contentsOf: screenshot)
        #expect(secondBytes != firstBytes, "office state change produced identical evidence")
        #expect(try Self.contentPixelCount(screenshot) >= 8)
    }

    @MainActor
    @Test("no surface is reported as rendered before it is projected")
    func unprojectedSurfaceIsNeverReportedRendered() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-evidence-none-\(UUID().uuidString)")
        let harness = try AppHarness.launch(
            root: root, mode: "--terminal", sessionID: "evidence-terminal", connections: 2
        )
        let socketPath = try #require(harness.socketPath)
        let screenshot = root.appendingPathComponent("terminal-surface.png")
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            screenshotPath: screenshot.path,
            emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }

        #expect(!events.contains("surface-rendered name=office"))
        #expect(!events.contains("surface-rendered name=browser_aside"))
        #expect(runtime.store.surface(named: "office") == nil)
    }
}

@MainActor
private func readySessionForEvidence(
    _ runtime: BirkinApplicationRuntime
) -> NativeReadySession? {
    switch runtime.connectionState {
    case .ready(let value), .fallback(.ready(let value)): value
    default: nil
    }
}
