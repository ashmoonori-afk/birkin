import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveProductSurfaces() async throws {
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
}
