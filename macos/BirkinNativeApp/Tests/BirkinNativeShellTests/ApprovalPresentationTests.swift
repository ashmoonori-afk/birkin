import AppKit
import BirkinNativeProtocol
import SwiftUI
import Testing

@testable import BirkinNativeShell

@Suite("Canonical approval cards")
@MainActor
struct ApprovalPresentationTests {
    @Test("risk card delegates explicit approve and reject commands")
    func decisionsDelegate() throws {
        let approval = try #require(ApprovalCardPresentation(item: approvalItem()))
        let availability = MutationAvailability(state: .ready(readySession()))
        var requests: [NativeCommandRequest] = []

        #expect(approval.risk == .high)
        #expect(approval.isSealed)
        #expect(approval.submit(
            .approve, availability: availability, commandAdvertised: true,
            expectedCursor: 12, sessionCapability: "capability",
            submit: { requests.append($0) }
        ))
        #expect(approval.submit(
            .reject, availability: availability, commandAdvertised: true,
            expectedCursor: 13, sessionCapability: "capability",
            submit: { requests.append($0) }
        ))
        #expect(requests.map(\.commandType) == ["approval.answer", "approval.answer"])
        #expect(requests[0].payload.string("decision") == "approve")
        #expect(requests[1].payload.string("decision") == "reject")
        #expect(requests.allSatisfy { $0.payload.string("approval_id") == "approval-1" })
    }

    @Test("approval mutations stay gated while disconnected")
    func disconnectedDoesNotSubmit() throws {
        let approval = try #require(ApprovalCardPresentation(item: approvalItem()))
        var requests: [NativeCommandRequest] = []
        #expect(!approval.submit(
            .approve, availability: MutationAvailability(state: .disconnected),
            commandAdvertised: true, expectedCursor: 12,
            sessionCapability: "capability", submit: { requests.append($0) }
        ))
        #expect(requests.isEmpty)
    }

    @Test("resolved approval exposes outcome without decision actions")
    func resolvedApprovalIsReadOnly() throws {
        let item: NativeJSONObject = [
            "id": .string("approval-1"), "summary": .string("Write release manifest"),
            "description": .string("One digest-bound file write"),
            "category": .string("operation"), "risk": .string("high"),
            "sealed": .bool(true), "decided": .bool(true),
            "status": .string("approved"), "kind": .string("approval"),
            "ui_state": .string("succeeded"),
            "receipt_ref": .string("exit 0: approved"),
        ]
        let approval = try #require(ApprovalCardPresentation(item: item))
        var requests: [NativeCommandRequest] = []

        #expect(approval.status == "approved")
        #expect(approval.receiptReference == "exit 0: approved")
        #expect(approval.availableDecisions.isEmpty)
        #expect(!approval.submit(
            .approve, availability: MutationAvailability(state: .ready(readySession())),
            commandAdvertised: true, expectedCursor: 14,
            sessionCapability: "capability", submit: { requests.append($0) }
        ))
        #expect(requests.isEmpty)
    }

    @Test("approval card renders screenshot evidence")
    func screenshotEvidence() throws {
        let approval = try #require(ApprovalCardPresentation(item: approvalItem()))
        let view = ApprovalCardView(
            presentation: approval, canDecide: true,
            approve: {}, reject: {}
        ).frame(width: 520, height: 260)
        let renderer = ImageRenderer(content: view)
        let image = try #require(renderer.nsImage)
        let bitmap = try #require(image.tiffRepresentation.flatMap(NSBitmapImageRep.init))
        let png = try #require(bitmap.representation(using: .png, properties: [:]))
        let output = evidenceDirectory().appendingPathComponent("approval-risk-card.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 8_000)
    }

    private func approvalItem() -> NativeJSONObject {
        [
            "id": .string("approval-1"), "summary": .string("Write release manifest"),
            "description": .string("One digest-bound file write"),
            "category": .string("operation"), "risk": .string("high"),
            "sealed": .bool(true), "decided": .bool(false),
            "status": .string("pending"), "kind": .string("approval"),
            "ui_state": .string("action_needed"), "created": .string("2026-08-20T00:00:00Z"),
        ]
    }

    private func readySession() -> NativeReadySession {
        let expiry = Date().addingTimeInterval(120)
        return NativeReadySession(
            instanceID: "instance", serverVersion: "1.0",
            sessionCapability: "capability", capabilityExpiresAt: expiry,
            capabilityHardExpiresAt: expiry,
            supportedCommands: ["approval.answer"], sessionPresets: []
        )
    }

    private func evidenceDirectory() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".omo/evidence/native-shell")
    }
}

private extension NativeJSONObject {
    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }
}
