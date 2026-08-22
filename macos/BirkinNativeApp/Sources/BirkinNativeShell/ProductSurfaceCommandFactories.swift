import BirkinNativeProtocol
import Foundation

public enum ComputerUseCommandFactory {
    public static func answer(
        decision: String,
        presentation: ComputerUsePresentation,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        guard ["approve", "reject"].contains(decision),
              presentation.consentState == "proposed",
              let grantID = presentation.grantID else { return nil }
        return request(
            type: "computer.answer",
            payload: ["grant_id": .string(grantID), "decision": .string(decision)],
            store: store, session: session
        )
    }

    public static func execute(
        presentation: ComputerUsePresentation,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        guard presentation.consentState == "approved",
              let grantID = presentation.grantID,
              let application = presentation.applicationRef,
              let window = presentation.windowRef else { return nil }
        return request(
            type: "computer.execute",
            payload: [
                "grant_id": .string(grantID),
                "application_ref": .string(application),
                "window_ref": .string(window),
            ],
            store: store, session: session
        )
    }

    private static func request(
        type: String, payload: NativeJSONObject,
        store: NativeProjectionStore, session: NativeReadySession
    ) -> NativeCommandRequest {
        ProductSurfaceRequest.make(
            prefix: "computer", type: type, payload: payload,
            viewID: "computer-use", store: store, session: session
        )
    }
}

public enum OfficeCommandFactory {
    public static func create(
        form: OfficeFormState,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        let name = form.outputName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !form.format.isEmpty, !name.isEmpty else { return nil }
        return request(
            type: "office.create",
            payload: [
                "format": .string(form.format),
                "content": .object(form.content),
                "output_name": .string(name),
            ], store: store, session: session
        )
    }

    public static func select(
        artifactID: String,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest {
        request(
            type: "office.select", payload: ["artifact_id": .string(artifactID)],
            store: store, session: session
        )
    }

    public static func open(
        presentation: OfficePresentation,
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        guard let document = presentation.selectedDocument else { return nil }
        return request(
            type: "office.open", payload: ["artifact": .object(document.raw)],
            store: store, session: session
        )
    }

    public static func convert(
        presentation: OfficePresentation,
        targetFormat: String,
        outputName: String,
        lossBudget: NativeJSONObject = [:],
        store: NativeProjectionStore,
        session: NativeReadySession
    ) -> NativeCommandRequest? {
        guard let document = presentation.selectedDocument,
              !targetFormat.isEmpty, !outputName.isEmpty else { return nil }
        return request(
            type: "office.convert",
            payload: [
                "artifact": .object(document.raw),
                "target_format": .string(targetFormat),
                "output_name": .string(outputName),
                "loss_budget": .object(lossBudget),
            ], store: store, session: session
        )
    }

    private static func request(
        type: String, payload: NativeJSONObject,
        store: NativeProjectionStore, session: NativeReadySession
    ) -> NativeCommandRequest {
        ProductSurfaceRequest.make(
            prefix: "office", type: type, payload: payload,
            viewID: "office", store: store, session: session
        )
    }
}

private enum ProductSurfaceRequest {
    static func make(
        prefix: String, type: String, payload: NativeJSONObject, viewID: String,
        store: NativeProjectionStore, session: NativeReadySession
    ) -> NativeCommandRequest {
        let identifier = "\(prefix)-\(UUID().uuidString.lowercased())"
        return NativeCommandRequest(
            frameID: "frame-\(identifier)", commandID: identifier,
            expectedCursor: store.latestAppliedCursor ?? 0,
            commandType: type, payload: payload,
            sessionCapability: session.sessionCapability, viewID: viewID
        )
    }
}
