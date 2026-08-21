import BirkinNativeProtocol
import Foundation

/// Builds the one Browser command Python registers.
///
/// The address comes from the person using the shell; the profile generation
/// and runtime revision come from the current Python projection, so a stale
/// projection produces a refusal from Python instead of a silent retarget.
public enum BrowserCommandFactory {
    public static func navigate(
        to address: String,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        let requested = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !requested.isEmpty,
              let surface = store.surface(named: "browser_aside"),
              case .object(let profile) = surface.payload["profile"],
              case .int(let generation) = profile["generation"],
              case .object(let runtime) = surface.payload["runtime"],
              case .int(let revision) = runtime["revision"] else { return nil }
        let identifier = "browser-\(UUID().uuidString.lowercased())"
        return NativeCommandRequest(
            frameID: "frame-\(identifier)",
            commandID: identifier,
            expectedCursor: store.latestAppliedCursor ?? 0,
            commandType: "browser.navigate",
            payload: [
                "url": .string(requested),
                "generation": .int(generation),
                "revision": .int(revision),
            ],
            sessionCapability: session.sessionCapability,
            viewID: "browser-aside"
        )
    }
}
