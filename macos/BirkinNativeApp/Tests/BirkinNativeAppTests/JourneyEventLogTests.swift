import Foundation
import Testing

@testable import BirkinNativeApp

@Suite("The QA journey log stays out of production runs and stays bounded")
struct JourneyEventLogTests {
    @Test("a run without QA mode keeps no journey log at all")
    @MainActor
    func productionRunHasNoJourneyLog() {
        #expect(PackagedJourneyConfiguration.discovered(in: [:]) == nil)
        #expect(BirkinApplicationHost.journeyEvents == nil)
    }

    @Test("QA mode is what creates a journey log")
    func qaModeCreatesConfiguration() {
        let configuration = PackagedJourneyConfiguration.discovered(in: [
            PackagedJourneyConfiguration.enabledKey: "1",
            PackagedJourneyConfiguration.evidenceKey: "/tmp/evidence",
            PackagedJourneyConfiguration.workspaceKey: "/tmp/workspace",
            PackagedJourneyConfiguration.browserURLKey: "http://127.0.0.1:8123/",
        ])
        #expect(configuration != nil)
    }

    @Test("retained lines never exceed the fixed window")
    func retentionStaysBounded() {
        let log = JourneyEventLog()
        let overflow = JourneyEventLog.retainedLineLimit + 500
        for index in 0..<overflow {
            log.record("event-\(index)")
        }
        let retained = log.recorded()
        #expect(retained.count == JourneyEventLog.retainedLineLimit)
        #expect(retained.last == "event-\(overflow - 1)")
    }

    @Test("persisted evidence redacts authority data without changing live waits")
    func persistedEvidenceIsRedacted() {
        let log = JourneyEventLog()
        log.record("command-error reason=Authorization: Bearer top-secret")
        log.record("jailed-import-applied reference=canonical-import-token")

        #expect(log.recorded().contains {
            $0.contains("canonical-import-token")
        })
        let persisted = log.persisted()
        #expect(persisted.allSatisfy { $0.contains("[REDACTED]") })
        #expect(persisted.allSatisfy {
            !$0.contains("top-secret") && !$0.contains("canonical-import-token")
        })
        let detail = JourneyEvidenceRedactor.redact(
            "access_token=token-value response=sk-1234567890"
        )
        #expect(detail == "access_token=[REDACTED] response=[REDACTED]")
    }

    @Test("stdout events redact secrets while live waits keep raw values")
    func stdoutEventsAreRedacted() {
        let raw = """
        command-error owner=owner-secret approval_id=approval-secret \
        payload={"session_capability":"capability-secret",\
        "refresh_token":"refresh-secret"} Authorization: Bearer bearer-secret
        """
        let log = JourneyEventLog()
        let outputCapture = JourneyOutputCapture()
        let diagnostics = NativeDiagnosticsLogger(
            isJourneyMode: true,
            journeyOutput: { outputCapture.write($0) }
        )
        log.record(raw)
        diagnostics.emit(raw)

        #expect(log.recorded() == [raw])
        let output = String(
            decoding: outputCapture.data(),
            as: UTF8.self
        )
        #expect(output.hasPrefix("BIRKIN_APP_EVENT command-error "))
        for secret in [
            "owner-secret", "approval-secret", "capability-secret",
            "refresh-secret", "bearer-secret",
        ] {
            #expect(!output.contains(secret))
        }
        #expect(output.contains("owner=[REDACTED]"))
        #expect(output.contains("session_capability=[REDACTED]"))
        #expect(output.contains("refresh_token=[REDACTED]"))
    }

    @Test("normal mode never writes event payloads to stdout")
    func productionStdoutIsSilent() {
        let outputCapture = JourneyOutputCapture()
        let diagnostics = NativeDiagnosticsLogger(
            isJourneyMode: false,
            journeyOutput: { outputCapture.write($0) }
        )
        diagnostics.emit(
            "connect-failed pid=4312 "
                + "executable=/Users/example/private/bin/birkin "
                + "reason=raw transport error owner=owner-secret"
        )

        #expect(outputCapture.data().isEmpty)
    }

    @Test("credential forms are completely redacted without suffix leaks")
    func credentialFormsAreFullyRedacted() {
        let redacted = JourneyEvidenceRedactor.redact(
            #"Authorization: Basic dXNlcjpwYXNz password="hunter two" api_key=AIza-secret"#
        )

        for secret in ["Basic", "dXNlcjpwYXNz", "hunter", "two", "AIza-secret"] {
            #expect(!redacted.contains(secret), "redacted=\(redacted)")
        }
        #expect(redacted == [
            "Authorization=[REDACTED]",
            "password=[REDACTED]",
            "api_key=[REDACTED]",
        ].joined(separator: " "))
    }

    @Test("ownership cleanup correlation is stable without exposing its token")
    func ownershipCorrelationIsNonSecret() {
        let token = "owner-secret"
        let digest = BirkinApplicationRuntime.ownershipCorrelationDigest(token)
        let output = String(
            decoding: NativeDiagnosticsLogger.journeyEventData(
                "bridge-started kind=owned pid=123 owner_sha256=\(digest)"
            ),
            as: UTF8.self
        )

        #expect(digest.count == 64)
        #expect(output.contains("owner_sha256=\(digest)"))
        #expect(!output.contains(token))
    }

    @MainActor
    @Test("receipt persistence reports an unwritable evidence root")
    func receiptWriteFailureIsPropagated() throws {
        let parent = FileManager.default.temporaryDirectory
            .appendingPathComponent("birkin-receipt-\(UUID().uuidString)")
        try FileManager.default.createDirectory(
            at: parent,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: parent) }
        let blockedRoot = parent.appendingPathComponent("blocked")
        try Data("not-a-directory".utf8).write(to: blockedRoot)
        let browserURL = try #require(
            URL(string: "http://127.0.0.1:8123/")
        )
        let runner = PackagedJourneyRunner(
            configuration: PackagedJourneyConfiguration(
                evidenceRoot: blockedRoot,
                workspaceRoot: parent.appendingPathComponent("workspace"),
                browserURL: browserURL
            ),
            runtime: BirkinApplicationRuntime(
                socketPath: "/private/tmp/unconnected.sock",
                ownedBridge: nil,
                emit: { _ in }
            ),
            events: JourneyEventLog()
        )

        #expect(throws: CocoaError.self) {
            try runner.writeReceipts()
        }
    }

    @MainActor
    @Test("fixed connection capture focus resolves without a scroll probe")
    func fixedConnectionCaptureFocusResolves() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("birkin-fixed-focus-\(UUID().uuidString)")
        let browserURL = try #require(
            URL(string: "http://127.0.0.1:8123/")
        )
        let runtime = BirkinApplicationRuntime(
            socketPath: "/private/tmp/unconnected.sock",
            ownedBridge: nil,
            windowCapture: PackagedWindowCapture(
                preflight: { true },
                windowIDs: { [1] },
                metadata: { _ in nil },
                image: { _ in nil }
            ),
            emit: { _ in }
        )
        let runner = PackagedJourneyRunner(
            configuration: PackagedJourneyConfiguration(
                evidenceRoot: root,
                workspaceRoot: root.appendingPathComponent("workspace"),
                browserURL: browserURL
            ),
            runtime: runtime,
            events: JourneyEventLog()
        )

        let generation = try await runner.focusForCapture(.connection)

        #expect(runtime.presentationModel.visibleGeneration == generation)
        #expect(runtime.presentationModel.target == .connection)
    }

    @Test("an absolute occurrence wait survives its match being trimmed away")
    func waitSurvivesTrimming() async throws {
        // Given: a bounded QA event log.
        let log = JourneyEventLog()

        // When: the first absolute wait completes, then its matching line
        // leaves retention before a new wait asks for the second occurrence.
        try await log.wait(for: "receipt:", onRegistered: {
            log.record("receipt:one")
        })
        for index in 0..<(JourneyEventLog.retainedLineLimit + 100) {
            log.record("noise-\(index)")
        }
        #expect(!log.recorded().contains("receipt:one"))

        // Then: the new wait remembers the prior absolute occurrence and
        // completes when the second receipt arrives.
        try await journeyDeadline("second absolute receipt", seconds: 1) {
            try await log.wait(for: "receipt:", occurrence: 2, onRegistered: {
                log.record("receipt:two")
            })
        }
    }
}

private final class JourneyOutputCapture: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes = Data()

    func write(_ data: Data) {
        lock.withLock { bytes.append(data) }
    }

    func data() -> Data {
        lock.withLock { bytes }
    }
}
