/// Every message kind the native protocol registers.
///
/// The raw values are the exact strings in `_KINDS` in
/// `birkin/native/protocol.py`; an unknown kind is refused rather than carried.
public enum NativeMessageKind: String, CaseIterable, Equatable, Sendable {
    case hello
    case ready
    case subscribe
    case snapshot
    case event
    case surfaceSnapshot = "surface_snapshot"
    case surfaceEvent = "surface_event"
    case command
    case receipt
    case error
    case capabilityRenewed = "capability.renewed"
    case streamDesynchronized = "stream.desynchronized"
    case ping
    case pong
    case goodbye
}
