/// The marker Python writes wherever a public projection must not carry a
/// secret. It is evidence that a value was withheld, never a usable value.
public enum NativeRedaction {
    public static let marker = "[REDACTED]"

    /// The value when it is genuinely usable, or nil when Python withheld it.
    public static func liveValue(_ value: String?) -> String? {
        guard let value, !value.isEmpty, value != marker else { return nil }
        return value
    }
}
