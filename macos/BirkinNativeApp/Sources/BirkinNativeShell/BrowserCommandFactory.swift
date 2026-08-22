import BirkinNativeProtocol
import Foundation

/// Builds Browser commands from the current Python-issued CAS identity.
public enum BrowserCommandFactory {
    public static func start(
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest {
        request(type: "browser.start", payload: [:], store: store, session: session)
    }

    public static func navigate(
        to address: String,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        let requested = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !requested.isEmpty, let identity = identity(store) else { return nil }
        return request(
            type: "browser.navigate",
            payload: [
                "url": .string(requested),
                "generation": .int(identity.generation),
                "revision": .int(identity.revision),
            ],
            store: store,
            session: session
        )
    }

    public static func back(store: NativeProjectionStore, session: NativeReadySession) -> NativeCommandRequest? {
        history(type: "browser.back", store: store, session: session)
    }

    public static func forward(store: NativeProjectionStore, session: NativeReadySession) -> NativeCommandRequest? {
        history(type: "browser.forward", store: store, session: session)
    }

    public static func reload(store: NativeProjectionStore, session: NativeReadySession) -> NativeCommandRequest? {
        history(type: "browser.reload", store: store, session: session)
    }

    public static func close(store: NativeProjectionStore, session: NativeReadySession) -> NativeCommandRequest {
        request(type: "browser.close", payload: [:], store: store, session: session)
    }

    private static func history(
        type: String,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        guard let identity = identity(store) else { return nil }
        return request(
            type: type,
            payload: [
                "generation": .int(identity.generation),
                "revision": .int(identity.revision),
            ],
            store: store,
            session: session
        )
    }

    private static func identity(_ store: NativeProjectionStore) -> (generation: Int, revision: Int)? {
        guard let surface = store.surface(named: "browser_aside"),
              case .object(let profile) = surface.payload["profile"],
              case .int(let generation) = profile["generation"],
              case .object(let runtime) = surface.payload["runtime"],
              case .int(let revision) = runtime["revision"] else { return nil }
        return (generation, revision)
    }

    private static func request(
        type: String,
        payload: NativeJSONObject,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest {
        let identifier = "browser-\(UUID().uuidString.lowercased())"
        return NativeCommandRequest(
            frameID: "frame-\(identifier)",
            commandID: identifier,
            expectedCursor: store.latestAppliedCursor ?? 0,
            commandType: type,
            payload: payload,
            sessionCapability: session.sessionCapability,
            viewID: "browser-aside"
        )
    }
}
