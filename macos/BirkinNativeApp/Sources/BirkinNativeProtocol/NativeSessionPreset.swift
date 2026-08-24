public struct NativeSessionPreset: Equatable, Sendable, Identifiable {
    public let id: String
    public let name: String
    public let prefill: String
    public let persistent: Bool
    public let order: Int

    public init(
        id: String,
        name: String,
        prefill: String,
        persistent: Bool,
        order: Int
    ) {
        self.id = id
        self.name = name
        self.prefill = prefill
        self.persistent = persistent
        self.order = order
    }

    static func decode(_ object: NativeJSONObject) throws -> NativeSessionPreset {
        guard Set(object.keys) == ["id", "name", "prefill", "persistent", "order"],
              case .string(let id) = object["id"],
              case .string(let name) = object["name"],
              case .string(let prefill) = object["prefill"],
              case .bool(let persistent) = object["persistent"],
              case .int(let order) = object["order"]
        else {
            throw NativeTransportError("session preset does not match the ready contract")
        }
        return NativeSessionPreset(
            id: id,
            name: name,
            prefill: prefill,
            persistent: persistent,
            order: order
        )
    }
}
