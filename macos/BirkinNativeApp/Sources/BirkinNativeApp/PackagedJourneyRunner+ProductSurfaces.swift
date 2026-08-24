import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveProductSurfaces() async throws {
        try await driveBrowser()

        runtime.submit(ProductSurfaceControl.officeNew)
        try await nextOutcome("office.create")
        try await journeyDeadline("office create surface") { [events] in
            try await events.wait(for: "surface-applied name=office", occurrence: 2)
        }
        let documents = officeDocumentCount()
        guard documents >= 1 else {
            throw JourneyError.refused("office document was not projected")
        }
        try await record("office-create-live", "documents=\(documents)")

        runtime.submit(ProductSurfaceControl.officeOpen)
        try await nextOutcome("office.open")
        try await journeyDeadline("office open surface") { [events] in
            try await events.wait(for: "surface-applied name=office", occurrence: 3)
        }
        try await record(
            "office-open-live",
            "documents=\(officeDocumentCount())"
        )

        let status = runtime.store.surface(named: "computer_use")
        guard status != nil else {
            throw JourneyError.refused("computer use surface missing")
        }
        try await record("computer-use-status", "projected=true")
    }

    private func officeDocumentCount() -> Int {
        guard let surface = runtime.store.surface(named: "office"),
              case .array(let documents) = surface.payload["documents"] else { return 0 }
        return documents.count
    }
}
