import Foundation

/// A ready bridge belongs to a different Birkin product revision.
public struct NativeProductVersionError: Error, Equatable, Sendable, CustomStringConvertible {
    public let expected: String
    public let actual: String

    public init(expected: String, actual: String) {
        self.expected = expected
        self.actual = actual
    }

    /// A log-safe rendering of the untrusted wire value.
    public var diagnosticActual: String {
        String(actual.prefix(64))
            .replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
    }

    public var description: String {
        "Birkin \(expected) requires the same bridge version; received "
            + "\(diagnosticActual). Reinstall Birkin or update the bridge override."
    }
}
