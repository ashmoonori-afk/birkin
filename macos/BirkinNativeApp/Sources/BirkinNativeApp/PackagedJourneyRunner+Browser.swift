import Foundation
import BirkinNativeProtocol
import BirkinNativeShell

extension PackagedJourneyRunner {
    func driveBrowser() async throws {
        let ready = try require(session, "session lost")
        guard ready.supportedCommands.contains("browser.start"),
              ready.supportedCommands.contains("browser.navigate") else {
            throw JourneyError.refused("Browser lifecycle commands were not advertised")
        }
        let initial = try require(
            runtime.store.surface(named: "browser_aside"),
            "initial Browser surface missing"
        )

        let start = BrowserCommandFactory.start(store: runtime.store, session: ready)
        runtime.submit(start)
        try await awaitBrowserCompletion(start, label: "browser.start")
        let started = try require(
            runtime.store.surface(named: "browser_aside"),
            "started Browser surface missing"
        )
        let startedPresentation = try require(
            BrowserAsidePresentation(store: runtime.store),
            "started Browser presentation invalid"
        )
        guard started.revision == initial.revision + 1,
              startedPresentation.isLive else {
            throw JourneyError.refused(
                "browser.start did not advance one live revision: "
                    + "\(initial.revision)->\(started.revision)"
            )
        }
        try await record(
            "browser-start-live",
            "surface_revision=\(initial.revision)->\(started.revision)"
        )

        let navigate = try require(
            BrowserCommandFactory.navigate(
                to: configuration.browserURL.absoluteString,
                store: runtime.store,
                session: try require(session, "session lost")
            ),
            "live Browser identity could not build navigation"
        )
        runtime.submit(navigate)
        try await awaitBrowserCompletion(navigate, label: "browser.navigate")
        let navigated = try require(
            runtime.store.surface(named: "browser_aside"),
            "navigated Browser surface missing"
        )
        let presentation = try require(
            BrowserAsidePresentation(store: runtime.store),
            "navigated Browser presentation invalid"
        )
        guard navigated.revision == started.revision + 1,
              presentation.isLive,
              presentation.frameReference != nil,
              presentation.frameRevision > startedPresentation.frameRevision,
              presentation.displayURL == browserOrigin(configuration.browserURL) else {
            throw JourneyError.refused(
                "browser.navigate did not project the local page at the next revision"
            )
        }
        try await record(
            "browser-navigate-live",
            "surface_revision=\(started.revision)->\(navigated.revision) "
                + "frame_revision=\(startedPresentation.frameRevision)"
                + "->\(presentation.frameRevision) url=\(presentation.displayURL)"
        )
    }

    private func awaitBrowserCompletion(
        _ request: NativeCommandRequest,
        label: String
    ) async throws {
        try await journeyDeadline("\(label) receipt") { [events] in
            try await events.wait(for: "command-receipt id=\(request.frameID)")
        }
        try await journeyDeadline("\(label) outcome") { [events] in
            try await events.wait(
                for: "projection-event type=command.completed "
                    + "command_id=\(request.commandID)"
            )
        }
        completions += 1
    }

    private func browserOrigin(_ url: URL) -> String? {
        guard var components = URLComponents(
            url: url, resolvingAgainstBaseURL: false
        ) else { return nil }
        components.path = "/"
        components.query = nil
        components.fragment = nil
        return components.url?.absoluteString
    }
}
