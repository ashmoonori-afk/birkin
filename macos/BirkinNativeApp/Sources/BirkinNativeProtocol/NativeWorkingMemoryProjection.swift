public struct NativeWorkingMemoryGoal: Equatable, Sendable {
    public let slug: String
    public let objective: String
    public let tokensUsed: Int
    public let status: String

    public init(slug: String, objective: String, tokensUsed: Int, status: String) {
        self.slug = slug
        self.objective = objective
        self.tokensUsed = tokensUsed
        self.status = status
    }
}

public struct NativeWorkingMemoryProjection: Equatable, Sendable {
    public var revision: Int
    public var goal: NativeWorkingMemoryGoal?
    public var fields: [String: [String]]
    public var filesEvidence: [NativeJSONObject]

    public init(
        revision: Int,
        goal: NativeWorkingMemoryGoal?,
        fields: [String: [String]],
        filesEvidence: [NativeJSONObject]
    ) {
        self.revision = revision
        self.goal = goal
        self.fields = fields
        self.filesEvidence = filesEvidence
    }

    var canonicalJSON: NativeJSONObject {
        var goalValue: NativeJSONValue = .null
        if let goal {
            goalValue = .object([
                "slug": .string(goal.slug),
                "objective": .string(goal.objective),
                "tokens_used": .int(goal.tokensUsed),
                "status": .string(goal.status),
            ])
        }
        var fieldValues = NativeJSONObject()
        for key in fields.keys.sorted() {
            try? fieldValues.append(
                key: key,
                value: .array((fields[key] ?? []).map(NativeJSONValue.string))
            )
        }
        return [
            "revision": .int(revision),
            "goal": goalValue,
            "fields": .object(fieldValues),
            "files_evidence": .array(filesEvidence.map(NativeJSONValue.object)),
        ]
    }
}
