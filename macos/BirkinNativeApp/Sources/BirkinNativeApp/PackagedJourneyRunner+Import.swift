import Foundation

extension PackagedJourneyRunner {
    func driveJailedImport() async throws {
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
}
