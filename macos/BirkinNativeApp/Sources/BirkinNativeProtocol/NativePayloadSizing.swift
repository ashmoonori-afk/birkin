public enum NativePayloadSizing {
    public static let defaultMaxPayloadBytes = 65_536

    public static func encodedByteCount(_ payload: NativeJSONObject) -> Int {
        NativeJSONSerializer.encode(object: payload).count
    }
}
