import AppKit
import Foundation

import BirkinNativeProtocol
import BirkinNativeShell

/// Drives the packaged application through its own controls and records what
/// each control produced.
@MainActor
final class PackagedJourneyRunner {
    private let configuration: PackagedJourneyConfiguration
    private let runtime: BirkinApplicationRuntime
    private let events: JourneyEventLog
    private var steps: [JourneyStep] = []
    private var completions = 0

    private let composer = ConversationComposerModel()
    private let terminal = TerminalControlModel()
    private let memory: WorkingMemoryEditorModel

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

    private var session: NativeReadySession? {
        switch runtime.connectionState {
        case .ready(let value), .fallback(.ready(let value)): value
        default: nil
        }
    }

    private var availability: MutationAvailability {
        MutationAvailability(state: runtime.connectionState, now: Date())
    }

    private var cursor: Int { runtime.store.latestAppliedCursor ?? 0 }

    /// Await the next canonical terminal outcome for a submitted command.
    ///
    /// Python decides whether a command completes or fails; both are canonical
    /// and both end the command. The journey asserts that an outcome arrived,
    /// then asserts the specific effect each step promises.
    private func nextOutcome(_ label: String) async throws {
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

    private func record(_ name: String, _ detail: String, shot: Bool = true) {
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
        try await driveMemoryAndImport()
        try await driveRecovery()
    }

    private func driveSessionAndChat(_ ready: NativeReadySession) async throws {
        // The New Session control, gated by what Python advertises.
        if ready.supportedCommands.contains("session.create") {
            runtime.submit(ShellMutationControl.newSession)
            try await nextOutcome("session.create")
            record("session-create", "submitted=true")
        } else {
            record(
                "session-select",
                "advertised_session=\(ready.currentSessionID) create_advertised=false"
            )
        }

        // The composer Send control.
        composer.draft = "Prove the packaged journey"
        guard composer.send(
            availability: availability,
            canSend: runtime.store.projection?.composer.canSend == true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("composer refused: \(composer.visibleReason ?? "")")
        }
        try await nextOutcome("chat.send")
        let conversation = runtime.store.projection?.conversation.count ?? 0
        guard conversation >= 1 else {
            throw JourneyError.refused("user message was not projected")
        }
        record(
            "chat-send-stream",
            "conversation_rows=\(conversation) outcome=\(runtime.lastCommandError == nil ? "completed" : "canonical_failure")"
        )
    }

    private func driveTerminal() async throws {
        guard terminal.requestTerminal(
            cwd: configuration.workspaceRoot.path,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("terminal create refused")
        }
        try await nextOutcome("terminal.create")
        let opened = try require(
            runtime.store.projection?.terminals.first, "no terminal projected"
        )
        guard let lease = opened.lease, lease != NativeRedaction.marker,
              opened.readOnly == false else {
            throw JourneyError.refused("terminal lease was not installed")
        }
        record("terminal-create-lease", "terminal=\(opened.terminalID)")

        guard terminal.sendInput(
            "printf packaged-journey-terminal\n",
            terminal: opened,
            expectedCursor: cursor,
            sessionCapability: try require(session, "session lost").sessionCapability,
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("terminal input refused")
        }
        try await nextOutcome("terminal.input")
        let screen = runtime.store.projection?.terminals.first?.screen ?? ""
        guard screen.contains("packaged-journey-terminal") else {
            throw JourneyError.refused("terminal output missing: \(screen.prefix(80))")
        }
        record("terminal-input-output", "screen_bytes=\(screen.utf8.count)")

        let activity = runtime.store.projection?
            .panels.first(where: { $0.key == "activity_logs" })?.items.count ?? 0
        record("activity-receipts", "activity_rows=\(activity)", shot: false)
    }

    private func driveProductSurfaces() async throws {
        let browserBefore = runtime.store.surface(named: "browser_aside")?.revision ?? 0
        runtime.submit(ProductSurfaceControl.browserNavigate(
            url: "http://127.0.0.1:8123/packaged-journey"
        ))
        try await nextOutcome("browser.navigate")
        let browserAfter = runtime.store.surface(named: "browser_aside")?.revision ?? 0
        let refusal = runtime.lastCommandError
        guard browserAfter > browserBefore || refusal != nil else {
            throw JourneyError.refused("browser command produced neither surface nor refusal")
        }
        record(
            "browser-navigate-live",
            "revision=\(browserBefore)->\(browserAfter) refusal=\(refusal == nil ? "none" : "canonical")"
        )

        runtime.submit(ProductSurfaceControl.officeNew)
        try await nextOutcome("office.create")
        try await journeyDeadline("office create surface") { [events] in
            try await events.wait(for: "surface-applied name=office", occurrence: 2)
        }
        let documents = officeDocumentCount()
        guard documents >= 1 else {
            throw JourneyError.refused("office document was not projected")
        }
        record("office-create-live", "documents=\(documents)")

        runtime.submit(ProductSurfaceControl.officeOpen)
        try await nextOutcome("office.open")
        try await journeyDeadline("office open surface") { [events] in
            try await events.wait(for: "surface-applied name=office", occurrence: 3)
        }
        record("office-open-live", "documents=\(officeDocumentCount())")

        let status = runtime.store.surface(named: "computer_use")
        guard status != nil else {
            throw JourneyError.refused("computer use surface missing")
        }
        record("computer-use-status", "projected=true")
    }

    private func officeDocumentCount() -> Int {
        guard let surface = runtime.store.surface(named: "office"),
              case .array(let documents) = surface.payload["documents"] else { return 0 }
        return documents.count
    }

    private func driveMemoryAndImport() async throws {
        let ready = try require(session, "session lost")
        if ready.supportedCommands.contains("memory.write") {
            try await driveMemoryClear()
        } else {
            record(
                "working-memory-gated",
                "memory_write_advertised=false revision=\(runtime.store.projection?.workingMemory.revision ?? -1)"
            )
        }
        try await driveJailedImport()
    }

    private func driveMemoryClear() async throws {
        guard memory.submitClear(
            availability: availability,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("memory clear refused: \(memory.visibleReason ?? "")")
        }
        try await nextOutcome("memory.write")
        record("working-memory-clear", "revision=\(runtime.store.projection?.workingMemory.revision ?? -1)")
    }

    private func driveJailedImport() async throws {
        let dropped = configuration.workspaceRoot
            .appendingPathComponent("packaged-journey-drop.txt")
        try Data("packaged journey import".utf8).write(to: dropped)
        guard runtime.jailedDrop.accept(
            urls: [dropped],
            availability: availability,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("jailed import refused")
        }
        try await nextOutcome("file.import")
        let reference = try require(runtime.jailedDrop.reference, "no import reference")
        guard runtime.jailedDrop.state == .imported else {
            throw JourneyError.refused("import chip state \(runtime.jailedDrop.state)")
        }
        record("jailed-import-chip", "token=\(reference.composerToken)")
    }

    private func driveRecovery() async throws {
        let pid = try require(runtime.ownedBridgeProcessIdentifier, "no owned bridge")
        _ = kill(pid, SIGKILL)
        try await journeyDeadline("owned bridge restart") { [events] in
            try await events.wait(for: "bridge-restarted kind=owned")
        }
        try await journeyDeadline("replay") { [events] in
            try await events.wait(for: "replayed")
        }
        let restarted = try require(
            runtime.ownedBridgeProcessIdentifier, "no restarted bridge"
        )
        guard restarted != pid else {
            throw JourneyError.refused("bridge pid did not change")
        }
        record("owned-bridge-restart-replay", "pid=\(pid)->\(restarted)")

        composer.draft = "Command after reconnect"
        guard composer.send(
            availability: availability,
            canSend: true,
            expectedCursor: cursor,
            session: try require(session, "session lost"),
            submit: { self.runtime.submit($0) }
        ) else {
            throw JourneyError.refused("post-reconnect send refused")
        }
        try await journeyDeadline("post reconnect receipt") { [events] in
            try await events.wait(for: "command-receipt", occurrence: 1)
        }
        record("post-reconnect-command", "cursor=\(cursor)")
    }

    private func require<T>(_ value: T?, _ reason: String) throws -> T {
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
