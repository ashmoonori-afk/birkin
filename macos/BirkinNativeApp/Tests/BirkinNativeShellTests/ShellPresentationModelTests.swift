import AppKit
import Foundation
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Shell focus presentation")
struct ShellPresentationModelTests {
    @MainActor
    @Test("an AppKit focus probe rejects a clipped target")
    func appKitProbeRejectsClippedTarget() {
        let scrollView = NSScrollView(
            frame: NSRect(x: 0, y: 0, width: 400, height: 300)
        )
        let documentView = FlippedFocusDocumentView(
            frame: NSRect(x: 0, y: 0, width: 400, height: 1_000)
        )
        let probe = ShellFocusVisibilityView(
            frame: NSRect(x: 0, y: 700, width: 400, height: 100)
        )
        documentView.addSubview(probe)
        scrollView.documentView = documentView
        scrollView.layoutSubtreeIfNeeded()

        #expect(!probe.isWithinVisibleViewport)

        scrollView.contentView.scroll(to: NSPoint(x: 0, y: 650))
        scrollView.reflectScrolledClipView(scrollView.contentView)

        #expect(probe.isWithinVisibleViewport)
    }

    @MainActor
    @Test("an unchanged focus probe reports visibility once")
    func unchangedProbeReportsOnce() {
        let probe = ShellFocusVisibilityView(
            frame: NSRect(x: 0, y: 0, width: 400, height: 100)
        )
        var reports: [Bool] = []

        probe.configure { reports.append($0) }
        probe.configure { reports.append($0) }

        #expect(reports == [true])
    }

    @MainActor
    @Test("an unreported focus request times out")
    func unreportedFocusTimesOut() async {
        let model = ShellPresentationModel()
        let generation = model.focus(.connection)

        await #expect(throws: ShellPresentationError.self) {
            try await model.waitUntilVisible(
                generation: generation,
                timeout: .milliseconds(20)
            )
        }
    }

    @MainActor
    @Test("a newer focus request supersedes an earlier registered waiter")
    func newerFocusSupersedesRegisteredWaiter() async {
        let model = ShellPresentationModel()
        let firstGeneration = model.focus(.section(.conversation))
        var secondGeneration: UInt64 = 0
        let waiter = Task { @MainActor in
            try await model.waitUntilVisible(
                generation: firstGeneration,
                timeout: .seconds(2),
                onWaiting: {
                    secondGeneration = model.focus(.section(.activity))
                }
            )
        }

        do {
            try await waiter.value
            Issue.record("superseded focus waiter completed successfully")
        } catch let error as ShellPresentationError {
            #expect(error == .superseded(
                generation: firstGeneration,
                by: secondGeneration
            ))
        } catch {
            Issue.record("unexpected focus waiter error: \(error)")
        }
    }

    @MainActor
    @Test("a superseded visible token cannot execute capture work")
    func supersededVisibleTokenCannotCapture() {
        let model = ShellPresentationModel()
        let generation = model.focus(.section(.activity))
        model.reportVisible(
            target: .section(.activity),
            generation: generation
        )
        _ = model.focus(.section(.browserAside))
        var captured = false

        #expect(throws: ShellPresentationError.self) {
            try model.withCurrentVisibility(
                target: .section(.activity),
                generation: generation
            ) {
                captured = true
            }
        }
        #expect(!captured)
    }

    @MainActor
    @Test("an already-mounted connection header focus is realized")
    func mountedConnectionFocusIsRealized() async throws {
        let now = Date(timeIntervalSince1970: 1_787_238_000)
        let session = NativeReadySession(
            instanceID: "mounted-focus-instance",
            serverVersion: "1.0",
            sessionCapability: "mounted-focus-capability",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
        let model = ShellPresentationModel()
        let hostingView = NSHostingView(rootView: NativeShellView(
            store: NativeProjectionStore(),
            connectionState: .ready(session),
            presentationModel: model
        ))
        hostingView.frame = NSRect(x: 0, y: 0, width: 1_280, height: 800)
        hostingView.layoutSubtreeIfNeeded()

        let generation = model.focus(.connection)
        try await model.waitUntilVisible(
            generation: generation,
            timeout: .seconds(2)
        )

        #expect(model.visibleGeneration == generation)
        #expect(model.target == .connection)
    }

    @MainActor
    @Test("a pre-mount accessibility panel focus is realized")
    func preMountPanelFocusIsRealized() async throws {
        let now = Date(timeIntervalSince1970: 1_787_238_000)
        let session = NativeReadySession(
            instanceID: "focus-instance",
            serverVersion: "1.0",
            sessionCapability: "focus-capability",
            capabilityExpiresAt: now.addingTimeInterval(60),
            capabilityHardExpiresAt: now.addingTimeInterval(120)
        )
        let model = ShellPresentationModel()
        let generation = model.focus(.section(.activity))
        let hostingView = NSHostingView(rootView: NativeShellView(
            store: NativeProjectionStore(),
            connectionState: .ready(session),
            presentationModel: model
        )
        .environment(\.dynamicTypeSize, .accessibility5))
        hostingView.frame = NSRect(x: 0, y: 0, width: 800, height: 640)
        hostingView.layoutSubtreeIfNeeded()

        try await model.waitUntilVisible(
            generation: generation,
            timeout: .seconds(2)
        )

        #expect(model.visibleGeneration == generation)
        #expect(model.target?.column == .context)
    }
}

private final class FlippedFocusDocumentView: NSView {
    override var isFlipped: Bool { true }
}
