extension PackagedJourneyRunner {
    func driveMemory() async throws {
        let ready = try require(session, "session lost")
        if ready.supportedCommands.contains("memory.write") {
            try await driveMemoryClear()
        } else {
            record(
                "working-memory-gated",
                "memory_write_advertised=false revision=\(runtime.store.projection?.workingMemory.revision ?? -1)"
            )
        }
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
}
