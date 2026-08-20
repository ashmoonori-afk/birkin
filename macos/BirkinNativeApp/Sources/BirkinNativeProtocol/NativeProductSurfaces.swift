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
    public let frameReference: String?
    public let frameRevision: Int
    public let refusal: String?

    public init?(store: NativeProjectionStore) {
        guard let surface = store.surface(named: "browser_aside"),
              let profile = surface.payload.object("profile"),
              let runtime = surface.payload.object("runtime"),
              let control = surface.payload.object("control"),
              let navigation = surface.payload.object("navigation"),
              let frame = surface.payload.object("frame"),
              let generation = profile.integer("generation"),
              let live = runtime.boolean("live"),
              let owner = control.string("owner_kind"),
              let epoch = control.integer("epoch"),
              let url = navigation.string("display_url"),
              let revision = frame.integer("revision") else { return nil }
        profileGeneration = generation
        isLive = live
        ownerKind = owner
        leaseEpoch = epoch
        leaseExpiresAt = control.optionalString("expires_at")
        displayURL = url
        frameReference = frame.optionalString("ref")
        frameRevision = revision
        refusal = surface.payload.optionalString("refusal")
    }
}

public struct ComputerUsePresentation: Equatable, Sendable {
    public let permissionPrompted: Bool
    public let consentState: String?
    public let oneShot: Bool
    public let applicationRef: String?
    public let windowRef: String?
    public let expiresAt: Date?
    public let countdownText: String?
    public let receipts: [NativeJSONObject]

    public init?(store: NativeProjectionStore, now: Date = Date()) {
        guard let surface = store.surface(named: "computer_use"),
              let status = surface.payload.object("status"),
              let prompted = status.boolean("permission_prompted") else { return nil }
        permissionPrompted = prompted
        receipts = surface.payload.objectArray("receipts") ?? []
        guard let consent = surface.payload.object("consent") else {
            consentState = nil
            oneShot = false
            applicationRef = nil
            windowRef = nil
            expiresAt = nil
            countdownText = nil
            return
        }
        consentState = consent.string("state")
        oneShot = consent.boolean("one_shot") ?? false
        applicationRef = consent.optionalString("application_ref")
        windowRef = consent.optionalString("window_ref")
        let expiry = consent.optionalString("expires_at").flatMap(Self.date)
        expiresAt = expiry
        if let expiry {
            let remaining = max(0, Int(expiry.timeIntervalSince(now).rounded(.up)))
            countdownText = remaining == 0 ? "Expired" : "\(remaining)s"
        } else {
            countdownText = nil
        }
    }

    private static func date(_ value: String) -> Date? {
        ISO8601DateFormatter().date(from: value)
    }
}

public struct OfficePresentation: Equatable, Sendable {
    public let formats: [String]
    public let documents: [NativeJSONObject]
    public let receipts: [NativeJSONObject]
    public let refusalCode: String?

    public init?(store: NativeProjectionStore) {
        guard let surface = store.surface(named: "office") else { return nil }
        formats = (surface.payload.objectArray("inventory") ?? []).compactMap {
            $0.string("format")
        }
        documents = surface.payload.objectArray("documents") ?? []
        receipts = surface.payload.objectArray("receipts") ?? []
        refusalCode = surface.payload.object("refusal")?.string("code")
    }
}

private extension NativeJSONObject {
    func object(_ key: String) -> NativeJSONObject? {
        guard case .object(let value) = self[key] else { return nil }
        return value
    }

    func objectArray(_ key: String) -> [NativeJSONObject]? {
        guard case .array(let values) = self[key] else { return nil }
        return values.compactMap {
            guard case .object(let value) = $0 else { return nil }
            return value
        }
    }

    func string(_ key: String) -> String? {
        guard case .string(let value) = self[key] else { return nil }
        return value
    }

    func optionalString(_ key: String) -> String? {
        string(key)
    }

    func integer(_ key: String) -> Int? {
        guard case .int(let value) = self[key] else { return nil }
        return value
    }

    func boolean(_ key: String) -> Bool? {
        guard case .bool(let value) = self[key] else { return nil }
        return value
    }
}
