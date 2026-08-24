/// A stable, bounded reason an embedded bridge cannot be trusted.
public struct OwnedBridgeDiscoveryError: Error, Equatable, Sendable, CustomStringConvertible {
    public enum Code: String, Equatable, Sendable {
        case manifestMissing = "embedded_manifest_missing"
        case manifestMalformed = "embedded_manifest_malformed"
        case manifestVersionMismatch = "embedded_version_mismatch"
        case manifestSourceDirty = "embedded_source_dirty"
        case architectureMissing = "embedded_architecture_missing"
        case helperMissing = "embedded_helper_missing"
        case helperInvalid = "embedded_helper_invalid"
        case helperHashMismatch = "embedded_helper_hash_mismatch"
    }

    public let code: Code

    init(_ code: Code) {
        self.code = code
    }

    public var description: String {
        switch code {
        case .manifestMissing:
            "The embedded bridge manifest is missing. Reinstall Birkin."
        case .manifestMalformed:
            "The embedded bridge manifest is invalid. Reinstall Birkin."
        case .manifestVersionMismatch:
            "The embedded bridge version does not match Birkin. Reinstall Birkin."
        case .manifestSourceDirty:
            "The embedded bridge was not built from a clean revision. Reinstall Birkin."
        case .architectureMissing:
            "No embedded bridge supports this Mac architecture. Reinstall Birkin."
        case .helperMissing:
            "The embedded bridge executable is missing. Reinstall Birkin."
        case .helperInvalid:
            "The embedded bridge executable is unsafe or unusable. Reinstall Birkin."
        case .helperHashMismatch:
            "The embedded bridge executable failed its integrity check. Reinstall Birkin."
        }
    }
}
