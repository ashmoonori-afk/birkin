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
