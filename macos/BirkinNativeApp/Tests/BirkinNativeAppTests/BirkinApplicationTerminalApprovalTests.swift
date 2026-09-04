import Foundation
import XCTest

@testable import BirkinNativeApp
import BirkinNativeProtocol
import BirkinNativeShell

@MainActor
final class BirkinApplicationTerminalApprovalTests: XCTestCase {
    func testExplicitApprovalThenTerminalIOAndReadOnlyReplay() async throws {
        let root = URL(fileURLWithPath: "/private/tmp/bk-terminal-approval-\(UUID().uuidString)")
        let workspace = root.appendingPathComponent("workspace-root")
        try FileManager.default.createDirectory(at: workspace, withIntermediateDirectories: true)
        let harness = try AppHarness.launch(
            root: root, connections: 2,
            environment: ["BIRKIN_HOME": root.appendingPathComponent("home").path]
        )
        let socketPath = try XCTUnwrap(harness.socketPath)
        let events = RuntimeEventRecorder()
        let runtime = BirkinApplicationRuntime(
            socketPath: socketPath, emit: { events.record($0) }
        )
        defer {
            runtime.stop()
            harness.terminate()
            try? FileManager.default.removeItem(at: root)
        }

        try await withTimeout("runtime start") { await runtime.start() }
        let session = try XCTUnwrap(readySession(runtime))
        XCTAssertTrue(session.supportedCommands.contains("approval.answer"))
        XCTAssertTrue(session.supportedCommands.contains("terminal.create"))
        let terminal = TerminalControlModel()
        var proposalRequest: NativeCommandRequest?
        XCTAssertTrue(terminal.requestTerminal(
            cwd: workspace.path,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: session.sessionCapability,
            submit: { proposalRequest = $0 }
        ))
        let proposed = try XCTUnwrap(proposalRequest)
        try await runtime.submitAwaitingTransport(proposed)
        try await withTimeout("approval requested") {
            try await events.wait(
                for: "projection-event type=approval.requested command_id=\(proposed.commandID)"
            )
        }
        try await withTimeout("terminal approval refusal") {
            try await events.wait(for: "command-error")
        }
        try await withTimeout("terminal proposal outcome") {
            try await events.wait(
                for: "projection-event type=command.failed command_id=\(proposed.commandID)"
            )
        }
        let approvalItem = try XCTUnwrap(runtime.store.projection?.panels
            .first(where: { $0.key == "approvals" })?.items.last)
        let approval = try XCTUnwrap(ApprovalCardPresentation(item: approvalItem))
        XCTAssertEqual(runtime.store.projection?.terminals.isEmpty, true)
        XCTAssertTrue(events.contains(
            "command-error id=\(proposed.frameID) "
                + "code=E_TERMINAL_APPROVAL_REQUIRED approval_id=\(approval.id)"
        ))
        let activityBeforeApproval = runtime.store.projection?.panels
            .first(where: { $0.key == "activity_logs" })?.items.count ?? 0

        var approvalRequest: NativeCommandRequest?
        XCTAssertTrue(approval.submit(
            .approve,
            availability: MutationAvailability(state: runtime.connectionState, now: Date()),
            commandAdvertised: true,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: try XCTUnwrap(readySession(runtime)).sessionCapability,
            submit: { approvalRequest = $0 }
        ))
        let approved = try XCTUnwrap(approvalRequest)
        try await runtime.submitAwaitingTransport(approved)
        try await withTimeout("approval receipt", events: events) {
            try await events.wait(for: "command-receipt id=\(approved.frameID)")
        }
        try await withTimeout("approval answer event") {
            try await events.wait(
                for: "projection-event type=approval.answered command_id=\(approved.commandID)"
            )
        }
        try await withTimeout("approval outcome") {
            try await events.wait(
                for: "projection-event type=command.completed command_id=\(approved.commandID)"
            )
        }
        let activityAfterApproval = runtime.store.projection?.panels
            .first(where: { $0.key == "activity_logs" })?.items.count ?? 0
        XCTAssertGreaterThan(activityAfterApproval, activityBeforeApproval)

        var createRequest: NativeCommandRequest?
        XCTAssertTrue(terminal.requestTerminal(
            cwd: workspace.path,
            approvalID: approval.id,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: try XCTUnwrap(readySession(runtime)).sessionCapability,
            submit: { createRequest = $0 }
        ))
        let create = try XCTUnwrap(createRequest)
        try await runtime.submitAwaitingTransport(create)
        try await withTimeout("terminal create receipt") {
            try await events.wait(for: "command-receipt id=\(create.frameID)")
        }
        try await withTimeout("terminal create outcome") {
            try await events.wait(
                for: "projection-event type=command.completed command_id=\(create.commandID)"
            )
        }
        let opened = try XCTUnwrap(runtime.store.projection?.terminals.first)
        XCTAssertFalse(opened.readOnly)
        XCTAssertFalse(try XCTUnwrap(opened.lease).isEmpty)

        var inputRequest: NativeCommandRequest?
        XCTAssertTrue(terminal.sendInput(
            "printf approval-terminal-proof\n",
            terminal: opened,
            expectedCursor: runtime.store.latestAppliedCursor ?? 0,
            sessionCapability: try XCTUnwrap(readySession(runtime)).sessionCapability,
            submit: { inputRequest = $0 }
        ))
        let input = try XCTUnwrap(inputRequest)
        try await runtime.submitAwaitingTransport(input)
        try await withTimeout("terminal input outcome") {
            try await events.wait(
                for: "projection-event type=command.completed command_id=\(input.commandID)"
            )
        }
        XCTAssertEqual(
            runtime.store.projection?.terminals.first?.screen
                .contains("approval-terminal-proof"),
            true
        )

        await runtime.stopAndWait()
        let replay = BirkinApplicationRuntime(socketPath: socketPath, emit: { _ in })
        defer { replay.stop() }
        try await withTimeout("replay runtime start") { await replay.start() }
        let restored = try XCTUnwrap(replay.store.projection?.terminals.first)
        XCTAssertTrue(restored.readOnly)
        XCTAssertNil(restored.lease)
        let replayControls = TerminalControlModel()
        XCTAssertFalse(replayControls.sendInput(
            "printf replay-bypass\n",
            terminal: restored,
            expectedCursor: replay.store.latestAppliedCursor ?? 0,
            sessionCapability: try XCTUnwrap(readySession(replay)).sessionCapability,
            submit: { replay.submit($0) }
        ))
        await replay.stopAndWait()
    }

    private func readySession(_ runtime: BirkinApplicationRuntime) -> NativeReadySession? {
        switch runtime.connectionState {
        case .ready(let session), .fallback(.ready(let session)): session
        default: nil
        }
    }
}
