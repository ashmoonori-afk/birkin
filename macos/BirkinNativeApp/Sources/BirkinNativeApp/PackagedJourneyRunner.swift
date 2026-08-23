import AppKit
import Foundation

import BirkinNativeProtocol
import BirkinNativeShell

/// Drives the packaged application through its own controls and records what
/// each control produced.
@MainActor
final class PackagedJourneyRunner {
    let configuration: PackagedJourneyConfiguration
    let runtime: BirkinApplicationRuntime
    let events: JourneyEventLog
    var steps: [JourneyStep] = []
    var completions = 0

    let composer = ConversationComposerModel()
    let terminal = TerminalControlModel()
    let memory: WorkingMemoryEditorModel

    init(
        configuration: PackagedJourneyConfiguration,
        runtime: BirkinApplicationRuntime,
        events: JourneyEventLog
    ) {
        self.configuration = configuration
        self.runtime = runtime
        self.events = events
        memory = WorkingMemoryEditorModel(
            authoritative: NativeWorkingMemoryProjection(
                revision: 0, goal: nil, fields: [:], filesEvidence: []
            )
        )
    }

    var session: NativeReadySession? {
        switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
    }

    var availability: MutationAvailability {
        MutationAvailability(state: runtime.connectionState, now: Date())
    }

    var cursor: Int { runtime.store.latestAppliedCursor ?? 0 }

    /// Await the next canonical terminal outcome for a submitted command.
    ///
    /// Python decides whether a command completes or fails; both are canonical
    /// and both end the command. The journey asserts that an outcome arrived,
    /// then asserts the specific effect each step promises.
    func nextOutcome(_ label: String) async throws {
        completions += 1
        let target = completions
        try await journeyDeadline(label) { [events] in
            try await events.wait(
                forAnyOf: [
                    "projection-event type=command.completed",
                    "projection-event type=command.failed",
                ],
                occurrence: target
            )
        }
    }

    func record(
        _ name: String,
        _ detail: String
    ) async throws {
        let target = focusTarget(for: name)
        let generation = try await focusForCapture(target)
        let url = configuration.evidenceRoot
            .appendingPathComponent("journey-\(steps.count + 1)-\(name).png")
        let capture = try runtime.captureEvidence(
            to: url,
            focusTarget: target.evidenceName,
            focusGeneration: generation
        )
        let evidenceDetail = [
            detail,
            "cjk=\(PackagedWindowCapture.cjkSpecimens.joined(separator: " "))",
        ].joined(separator: " ")
        steps.append(JourneyStep(
            name: name,
            state: name,
            surface: target.evidenceName,
            succeeded: true,
            detail: evidenceDetail,
            screenshot: url.lastPathComponent,
            capture: capture
        ))
        runtime.emitJourney("journey-step name=\(name) detail=\(evidenceDetail)")
    }

    func focusForCapture(_ target: ShellFocusTarget) async throws -> UInt64 {
        let generation = runtime.presentationModel.focus(target)
        if target == .connection {
            runtime.presentationModel.reportVisible(
                target: target,
                generation: generation
            )
        } else {
            try await journeyDeadline("focus \(target.evidenceName)") {
                try await self.runtime.presentationModel.waitUntilVisible(
                    generation: generation
                )
            }
        }
        return generation
    }

    private func fail(_ name: String, _ detail: String) {
        steps.append(JourneyStep(
            name: name,
            state: "failed",
            surface: "journey",
            succeeded: false,
            detail: detail,
            screenshot: nil,
            capture: nil
        ))
        runtime.emitJourney("journey-step-failed name=\(name) detail=\(detail)")
    }

    func run() async {
        do {
            try await drive()
        } catch {
            fail("journey", String(describing: error))
        }
        var succeeded = steps.allSatisfy(\.succeeded)
        let ownedBridge = runtime.ownedBridgeProcessIdentifier
        do {
            try writeReceipts()
        } catch {
            succeeded = false
            runtime.emitJourney(
                "journey-receipt-write-failed error=\(String(describing: error))"
            )
        }
        runtime.stop()
        if let ownedBridge {
            // Leave nothing running: wait for the bridge this app owned to be
            // reaped before the process exits.
            try? await journeyDeadline("owned bridge exit", seconds: 20) {
                while kill(ownedBridge, 0) == 0 {
                    try await Task.sleep(for: .milliseconds(20))
                }
            }
        }
        exit(succeeded ? 0 : 1)
    }

    private func drive() async throws {
        try await journeyDeadline("connected") { [events] in
            try await events.wait(for: "connected transport=uds")
        }
        let ready = try require(session, "no ready session")
        try await record(
            "connected",
            "session=\(ready.currentSessionID)"
        )

        try await driveSessionAndChat(ready)
        try await driveTerminal()
        try await driveProductSurfaces()
        try await driveMemory()
        try await driveJailedImport()
        try await driveRecovery()
    }

    func require<T>(_ value: T?, _ reason: String) throws -> T {
        guard let value else { throw JourneyError.refused(reason) }
        return value
    }

    private func focusTarget(for step: String) -> ShellFocusTarget {
        switch step {
        case "connected":
            .connection
        case "session-create", "post-reconnect-command":
            .section(.sessions)
        case "chat-send-stream":
            .section(.conversation)
        case "working-memory-clear", "working-memory-gated":
            .section(.workingMemory)
        case "terminal-approval-requested", "terminal-approval-approved":
            .section(.approvals)
        case "terminal-create-lease", "terminal-input-output",
             "terminal-replay-refusal":
            .section(.terminal)
        case "activity-receipts":
            .section(.activity)
        case "browser-start-live", "browser-navigate-live":
            .section(.browserAside)
        case "office-create-live", "office-open-live":
            .section(.office)
        case "computer-use-status":
            .section(.computerUse)
        case "jailed-import-chip":
            .section(.composer)
        default:
            .section(.conversation)
        }
    }

    func writeReceipts() throws {
        let payload: [String: Any] = [
            "schema": 2,
            "origin": ProcessInfo.processInfo.environment[
                "BIRKIN_NATIVE_JOURNEY_ORIGIN"
            ] ?? "built-app",
            "origin_mount": ProcessInfo.processInfo.environment[
                "BIRKIN_NATIVE_JOURNEY_MOUNT"
            ] ?? "",
            "origin_image": ProcessInfo.processInfo.environment[
                "BIRKIN_NATIVE_JOURNEY_IMAGE"
            ] ?? "",
            "steps": steps.map {
                var step: [String: Any] = [
                    "name": $0.name,
                    "succeeded": $0.succeeded,
                    "state": $0.state,
                    "surface": $0.surface,
                    "detail": JourneyEvidenceRedactor.redact($0.detail),
                    "screenshot": $0.screenshot ?? "",
                ]
                if let capture = $0.capture {
                    step["capture"] = [
                        "source": capture.source,
                        "owner_pid": capture.ownerPID,
                        "window_number": capture.windowNumber,
                        "point_width": capture.pointWidth,
                        "point_height": capture.pointHeight,
                        "pixel_width": capture.pixelWidth,
                        "pixel_height": capture.pixelHeight,
                        "focus_target": capture.focusTarget,
                        "focus_generation": capture.focusGeneration,
                        "executable_path": capture.executablePath,
                        "png_sha256": capture.pngSHA256,
                        "cjk_ocr_markers": capture.cjkOCRMarkers,
                    ]
                }
                return step
            },
            "succeeded": steps.allSatisfy(\.succeeded),
            "events": events.persisted(),
        ]
        let url = configuration.evidenceRoot
            .appendingPathComponent("packaged-journey-receipts.json")
        try FileManager.default.createDirectory(
            at: configuration.evidenceRoot, withIntermediateDirectories: true
        )
        let data = try JSONSerialization.data(
            withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]
        )
        try data.write(to: url, options: .atomic)
    }

}
