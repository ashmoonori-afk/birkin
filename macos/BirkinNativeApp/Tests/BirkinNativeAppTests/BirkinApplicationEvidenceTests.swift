import AppKit
import Combine
import Foundation
import SwiftUI
import Testing
import XCTest

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
        let captureState = EvidenceCaptureState()
        let captureView = EvidenceCaptureView()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            screenshotPath: screenshot.path,
            windowCapture: testCapture(captureView) {
                captureState.visibleGeneration =
                    captureState.runtime?.presentationModel.visibleGeneration ?? 0
            },
            emit: { events.record($0) }
        )
        captureState.runtime = runtime
        runtime.presentationModel.focus(.section(.activity))
        let hostedView = host(runtime, captureView: captureView)
        let layoutDriver = driveLayout(
            for: runtime,
            view: hostedView
        )
        defer {
            layoutDriver.cancel()
            captureView.view = nil
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
        #expect(
            captureState.visibleGeneration > 0,
            "Configured evidence must wait until the live shell reports its layout visible"
        )
        let firstColours = try Self.contentPixelCount(screenshot)
        #expect(firstColours >= 8, "rendered evidence has \(firstColours) colours")
        let firstBytes = try Data(contentsOf: screenshot)

        let ready = try #require(readySessionForEvidence(runtime))
        runtime.presentationModel.focus(.section(.browserAside))
        let start = BrowserCommandFactory.start(store: runtime.store, session: ready)
        runtime.submit(start)
        try await withTimeout("Browser start outcome") {
            try await events.wait(
                for: "projection-event type=command.completed command_id=\(start.commandID)"
            )
        }
        try await withTimeout("Browser surface update") {
            try await events.wait(for: "surface-rendered name=browser_aside", occurrence: 2)
        }

        let secondBytes = try Data(contentsOf: screenshot)
        #expect(secondBytes != firstBytes, "Browser state change produced identical evidence")
        #expect(try Self.contentPixelCount(screenshot) >= 8)

        runtime.stop()
        try await withTimeout("evidence bridge cleanup", seconds: 60) {
            await Task.detached { harness.process.waitUntilExit() }.value
        }
        #expect(!harness.process.isRunning)
    }

    @MainActor
    private func host(
        _ runtime: BirkinApplicationRuntime,
        captureView: EvidenceCaptureView
    ) -> NSView {
        let snapshotView = NSHostingView(rootView: EvidenceRuntimeView(runtime: runtime))
        snapshotView.frame = NSRect(x: 0, y: 0, width: 1_280, height: 800)
        snapshotView.layoutSubtreeIfNeeded()
        captureView.view = snapshotView
        return snapshotView
    }

    @MainActor
    private func driveLayout(
        for runtime: BirkinApplicationRuntime,
        view: NSView
    ) -> AnyCancellable {
        runtime.presentationModel.$requestGeneration
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { _ in view.layoutSubtreeIfNeeded() }
    }

    @MainActor
    private func testCapture(_ view: EvidenceCaptureView) -> PackagedWindowCapture {
        testCapture(view, beforeImage: {})
    }

    @MainActor
    private func testCapture(
        _ captureView: EvidenceCaptureView,
        beforeImage: @escaping @MainActor @Sendable () -> Void
    ) -> PackagedWindowCapture {
        PackagedWindowCapture(
            preflight: { true },
            windowIDs: { [1] },
            metadata: { _ in .valid },
            image: { _ in
                beforeImage()
                guard let view = captureView.view,
                      let representation = view.bitmapImageRepForCachingDisplay(
                          in: view.bounds
                      ) else { return nil }
                view.cacheDisplay(in: view.bounds, to: representation)
                return representation.cgImage
            }
        )
    }
}

@MainActor
final class BirkinApplicationUnprojectedSurfaceTests: XCTestCase {
    func testNoSurfaceIsReportedRenderedBeforeProjection() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-evidence-none-\(UUID().uuidString)")
        let harness = try AppHarness.launch(
            root: root, mode: "--terminal", sessionID: "evidence-terminal", connections: 2
        )
        let socketPath = try XCTUnwrap(harness.socketPath)
        let screenshot = root.appendingPathComponent("terminal-surface.png")
        let events = RuntimeEventRecorder()
        let captureView = EvidenceCaptureView()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath,
            screenshotPath: screenshot.path,
            windowCapture: testCapture(captureView),
            emit: { events.record($0) }
        )
        runtime.presentationModel.focus(.section(.activity))
        let hostingView = NSHostingView(rootView: EvidenceRuntimeView(runtime: runtime))
        hostingView.frame = NSRect(x: 0, y: 0, width: 1_280, height: 800)
        hostingView.layoutSubtreeIfNeeded()
        captureView.view = hostingView
        let focusStub = runtime.presentationModel.$requestGeneration
            .dropFirst()
            .receive(on: DispatchQueue.main)
            .sink { [presentationModel = runtime.presentationModel] generation in
                guard let target = presentationModel.target else { return }
                presentationModel.reportVisible(target: target, generation: generation)
            }
        defer {
            focusStub.cancel()
            captureView.view = nil
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }

        XCTAssertFalse(events.contains("surface-rendered name=office"))
        XCTAssertFalse(events.contains("surface-rendered name=browser_aside"))
        XCTAssertNil(runtime.store.surface(named: "office"))
    }

    private func testCapture(
        _ captureView: EvidenceCaptureView
    ) -> PackagedWindowCapture {
        PackagedWindowCapture(
            preflight: { true },
            windowIDs: { [1] },
            metadata: { _ in .valid },
            image: { _ in
                guard let view = captureView.view,
                      let representation = view.bitmapImageRepForCachingDisplay(
                          in: view.bounds
                      ) else { return nil }
                view.cacheDisplay(in: view.bounds, to: representation)
                return representation.cgImage
            }
        )
    }
}

@MainActor
private final class EvidenceCaptureState {
    weak var runtime: BirkinApplicationRuntime?
    var visibleGeneration: UInt64 = 0
}

@MainActor
private final class EvidenceCaptureView {
    var view: NSView?
}

private struct EvidenceRuntimeView: View {
    @ObservedObject var runtime: BirkinApplicationRuntime

    var body: some View {
        NativeShellView(
            store: runtime.store,
            connectionState: runtime.connectionState,
            jailedDrop: runtime.jailedDrop,
            presentationModel: runtime.presentationModel
        )
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
