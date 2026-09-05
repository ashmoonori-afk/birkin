import Foundation

public struct NativeSurfaceProjection: Equatable, Sendable {
    public let name: String
    public let revision: Int
    public let payload: NativeJSONObject
}

public struct BrowserAsidePresentation: Equatable, Sendable {
    public let profileGeneration: Int
    public let isLive: Bool
    public let ownerKind: String
    public let leaseEpoch: Int
    public let leaseExpiresAt: String?
    public let displayURL: String
    public let isLoading: Bool
    public let historyEntries: [String]
    public let historyIndex: Int
    public let canGoBack: Bool
    public let canGoForward: Bool
    public let frameReference: String?
    public let frameRevision: Int
    public let frameDigest: String?
    public let frameMediaType: String?
    public let frameMaximumBytes: Int
    public let refusal: String?

    public init?(store: NativeProjectionStore) {
        guard let surface = store.surface(named: "browser_aside"),
              let profile = surface.payload.surfaceObject("profile"),
              let runtime = surface.payload.surfaceObject("runtime"),
              let control = surface.payload.surfaceObject("control"),
              let navigation = surface.payload.surfaceObject("navigation"),
              let frame = surface.payload.surfaceObject("frame"),
              let generation = profile.surfaceInteger("generation"),
              let live = runtime.surfaceBoolean("live"),
              let owner = control.surfaceString("owner_kind"),
              let epoch = control.surfaceInteger("epoch"),
              let url = navigation.surfaceString("display_url"),
              let revision = frame.surfaceInteger("revision") else { return nil }
        profileGeneration = generation
        isLive = live
        ownerKind = owner
        leaseEpoch = epoch
        leaseExpiresAt = control.surfaceOptionalString("expires_at")
        displayURL = url
        isLoading = navigation.surfaceBoolean("loading") ?? false
        let history = navigation.surfaceObject("history")
        historyEntries = history?.surfaceStringArray("entries") ?? []
        historyIndex = history?.surfaceInteger("index") ?? -1
        canGoBack = history?.surfaceBoolean("can_go_back") ?? false
        canGoForward = history?.surfaceBoolean("can_go_forward") ?? false
        frameReference = frame.surfaceOptionalString("ref")
        frameRevision = revision
        frameDigest = frame.surfaceOptionalString("digest")
        frameMediaType = frame.surfaceOptionalString("media_type")
        frameMaximumBytes = frame.surfaceInteger("max_bytes") ?? 0
        refusal = surface.payload.surfaceOptionalString("refusal")
    }
}

public struct ComputerUseGuidancePresentation: Equatable, Identifiable, Sendable {
    public let id: String
    public let permission: String
    public let responsibleProcess: String
    public let settingsPath: String

    init?(_ raw: NativeJSONObject) {
        guard let capability = raw.surfaceString("capability"), !capability.isEmpty,
              let permission = raw.surfaceString("permission"), !permission.isEmpty,
              let responsibleProcess = raw.surfaceString("responsible_process"),
              !responsibleProcess.isEmpty,
              let settingsPath = raw.surfaceString("settings_path"), !settingsPath.isEmpty else {
            return nil
        }
        id = capability
        self.permission = permission
        self.responsibleProcess = responsibleProcess
        self.settingsPath = settingsPath
    }
}

public struct ComputerUsePresentation: Equatable, Sendable {
    public let permissionPrompted: Bool
    public let accessibilityStatus: String
    public let screenRecordingStatus: String
    public let backendStatus: String
    public let bindingStatus: String
    public let guidance: [ComputerUseGuidancePresentation]
    public let grantID: String?
    public let consentState: String?
    public let oneShot: Bool
    public let action: String?
    public let applicationRef: String?
    public let windowRef: String?
    public let expiresAt: Date?
    public let countdownText: String?
    public let receipts: [NativeJSONObject]

    public init?(store: NativeProjectionStore, now: Date = Date()) {
        guard let surface = store.surface(named: "computer_use"),
              let status = surface.payload.surfaceObject("status"),
              let prompted = status.surfaceBoolean("permission_prompted") else { return nil }
        permissionPrompted = prompted
        let permissions = status.surfaceObject("permissions")
        accessibilityStatus = permissions?.surfaceString("accessibility") ?? "unknown"
        screenRecordingStatus = permissions?.surfaceString("screen_capture") ?? "unknown"
        backendStatus = status.surfaceObject("backend")?.surfaceString("state") ?? "unknown"
        bindingStatus = status.surfaceObject("binding")?.surfaceString("state") ?? "unknown"
        guidance = (status.surfaceObjectArray("guidance") ?? [])
            .compactMap(ComputerUseGuidancePresentation.init)
        receipts = surface.payload.surfaceObjectArray("receipts") ?? []
        guard let consent = surface.payload.surfaceObject("consent") else {
            grantID = nil; consentState = nil; oneShot = false; action = nil
            applicationRef = nil; windowRef = nil; expiresAt = nil; countdownText = nil
            return
        }
        grantID = consent.surfaceOptionalString("grant_id")
        consentState = consent.surfaceString("state")
        oneShot = consent.surfaceBoolean("one_shot") ?? false
        action = consent.surfaceOptionalString("action")
        applicationRef = consent.surfaceOptionalString("application_ref")
        windowRef = consent.surfaceOptionalString("window_ref")
        let expiry = consent.surfaceOptionalString("expires_at").flatMap(Self.date)
        expiresAt = expiry
        if let expiry {
            let remaining = max(0, Int(expiry.timeIntervalSince(now).rounded(.up)))
            countdownText = remaining == 0 ? "Expired" : "\(remaining)s"
        } else { countdownText = nil }
    }

    private static func date(_ value: String) -> Date? {
        ISO8601DateFormatter().date(from: value)
    }
}

public struct OfficeFormState: Equatable, Sendable {
    public var format: String
    public var outputName: String
    public var content: NativeJSONObject

    public init(format: String = "docx", outputName: String = "", content: NativeJSONObject = [:]) {
        self.format = format
        self.outputName = outputName
        self.content = content
    }
}

public struct OfficeDocumentPresentation: Equatable, Sendable, Identifiable {
    public let id: String
    public let raw: NativeJSONObject
    public let provenance: NativeJSONObject?
    public let conversion: NativeJSONObject?
    public let activeContent: [NativeJSONObject]

    init?(_ raw: NativeJSONObject) {
        guard let id = raw.surfaceString("artifact_id") else { return nil }
        self.id = id
        self.raw = raw
        provenance = raw.surfaceObject("provenance")
        conversion = raw.surfaceObject("conversion")
        activeContent = raw.surfaceObjectArray("active_content") ?? []
    }
}

public struct OfficePresentation: Equatable, Sendable {
    public let formats: [String]
    public let form: OfficeFormState
    public let selectedArtifactID: String?
    public let documentPresentations: [OfficeDocumentPresentation]
    public let documents: [NativeJSONObject]
    public let receipts: [NativeJSONObject]
    public let refusalCode: String?

    public var selectedDocument: OfficeDocumentPresentation? {
        documentPresentations.first { $0.id == selectedArtifactID }
    }

    public init?(store: NativeProjectionStore) {
        guard let surface = store.surface(named: "office") else { return nil }
        formats = (surface.payload.surfaceObjectArray("inventory") ?? []).compactMap { $0.surfaceString("format") }
        if let state = surface.payload.surfaceObject("form") {
            form = OfficeFormState(
                format: state.surfaceString("format") ?? formats.first ?? "docx",
                outputName: state.surfaceString("output_name") ?? "",
                content: state.surfaceObject("content") ?? [:]
            )
        } else { form = OfficeFormState(format: formats.first ?? "docx") }
        selectedArtifactID = surface.payload.surfaceOptionalString("selected_artifact_id")
        documents = surface.payload.surfaceObjectArray("documents") ?? []
        documentPresentations = documents.compactMap(OfficeDocumentPresentation.init)
        receipts = surface.payload.surfaceObjectArray("receipts") ?? []
        refusalCode = surface.payload.surfaceObject("refusal")?.surfaceString("code")
    }
}

extension NativeJSONObject {
    func surfaceObject(_ key: String) -> NativeJSONObject? {
        guard case .object(let value) = self[key] else { return nil }
        return value
    }

    func surfaceObjectArray(_ key: String) -> [NativeJSONObject]? {
        guard case .array(let values) = self[key] else { return nil }
        return values.compactMap { if case .object(let value) = $0 { value } else { nil } }
    }

    func surfaceStringArray(_ key: String) -> [String]? {
        guard case .array(let values) = self[key] else { return nil }
        return values.compactMap { if case .string(let value) = $0 { value } else { nil } }
    }

    func surfaceString(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func surfaceOptionalString(_ key: String) -> String? { surfaceString(key) }

    func surfaceInteger(_ key: String) -> Int? {
        guard case .int(let value) = self[key] else { return nil }
        return value
    }

    func surfaceBoolean(_ key: String) -> Bool? {
        guard case .bool(let value) = self[key] else { return nil }
        return value
    }
}
