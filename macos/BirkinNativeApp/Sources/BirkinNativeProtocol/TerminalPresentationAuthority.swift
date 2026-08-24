public enum TerminalMutationControl: String, CaseIterable, Hashable, Sendable {
    case input
    case run
    case interrupt
    case close
    case closeConfirmation
}

public struct TerminalPresentationAuthority: Equatable, Sendable {
    public let visibleMutationControls: Set<TerminalMutationControl>
    public let showsReadOnlyReplayLabel: Bool
    public let statusLabel: String

    public init(
        terminal: NativeTerminalProjection,
        capabilityAllowsMutation: Bool
    ) {
        let hasLiveLease = terminal.lease?.isEmpty == false
        let isMutable =
            capabilityAllowsMutation
            && terminal.state == "running"
            && !terminal.readOnly
            && hasLiveLease
        visibleMutationControls = isMutable ? Set(TerminalMutationControl.allCases) : []
        showsReadOnlyReplayLabel = terminal.readOnly
        statusLabel = terminal.readOnly ? "Read-only replay" : terminal.state.uppercased()
    }

    public func shows(_ control: TerminalMutationControl) -> Bool {
        visibleMutationControls.contains(control)
    }
}
