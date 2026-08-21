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

    func record(_ name: String, _ detail: String, shot: Bool = true) {
        var screenshot: String?
        if shot, let session {
            let url = configuration.evidenceRoot
                .appendingPathComponent("journey-\(steps.count + 1)-\(name).png")
            if (try? runtime.renderEvidence(to: url, session: session)) == true {
                screenshot = url.lastPathComponent
            }
        }
        steps.append(JourneyStep(
            name: name, succeeded: true, detail: detail, screenshot: screenshot
        ))
        runtime.emitJourney("journey-step name=\(name) detail=\(detail)")
    }

    private func fail(_ name: String, _ detail: String) {
        steps.append(JourneyStep(
            name: name, succeeded: false, detail: detail, screenshot: nil
        ))
        runtime.emitJourney("journey-step-failed name=\(name) detail=\(detail)")
    }

    func run() async {
        do {
            try await drive()
        } catch {
            fail("journey", String(describing: error))
        }
        let ownedBridge = runtime.ownedBridgeProcessIdentifier
        writeReceipts()
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
        exit(steps.allSatisfy(\.succeeded) ? 0 : 1)
    }

    private func drive() async throws {
        try await journeyDeadline("connected") { [events] in
            try await events.wait(for: "connected transport=uds")
        }
        let ready = try require(session, "no ready session")
        record("connected", "session=\(ready.currentSessionID)")

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

    private func writeReceipts() {
        let payload: [String: Any] = [
            "steps": steps.map {
                [
                    "name": $0.name, "succeeded": $0.succeeded,
                    "detail": $0.detail, "screenshot": $0.screenshot ?? "",
                ]
            },
            "succeeded": steps.allSatisfy(\.succeeded),
            "events": events.recorded(),
        ]
        let url = configuration.evidenceRoot
            .appendingPathComponent("packaged-journey-receipts.json")
        try? FileManager.default.createDirectory(
            at: configuration.evidenceRoot, withIntermediateDirectories: true
        )
        if let data = try? JSONSerialization.data(
            withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]
        ) {
            try? data.write(to: url, options: .atomic)
        }
    }
}
