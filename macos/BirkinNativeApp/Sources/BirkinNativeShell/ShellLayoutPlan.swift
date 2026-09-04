import SwiftUI

public enum ShellLayoutMode: Equatable, Sendable {
    case threeColumns
    case panelNavigation
}

public struct ShellColumnWidthPolicy: Equatable, Sendable {
    public let minimum: CGFloat
    public let ideal: CGFloat
    public let maximum: CGFloat
    public let layoutPriority: Double
}

public struct ShellLayoutPlan: Equatable, Sendable {
    public let mode: ShellLayoutMode
    public let statusAllowsVerticalReflow: Bool
    public let columnHeaderLineLimit: Int?
    public let columnHeadersUseFixedVerticalSize: Bool
    public let columnsScrollIndependently: Bool

    public init(windowWidth: CGFloat, dynamicTypeSize: DynamicTypeSize) {
        mode = dynamicTypeSize.isAccessibilitySize || windowWidth < 960
            ? .panelNavigation
            : .threeColumns
        statusAllowsVerticalReflow = true
        columnHeaderLineLimit = nil
        columnHeadersUseFixedVerticalSize = true
        columnsScrollIndependently = true
    }

    public func width(for column: ShellColumnID) -> ShellColumnWidthPolicy {
        switch column {
        case .navigation:
            ShellColumnWidthPolicy(
                minimum: 240, ideal: 280, maximum: 420, layoutPriority: 1
            )
        case .primary:
            ShellColumnWidthPolicy(
                minimum: 400, ideal: 560, maximum: 900, layoutPriority: 2
            )
        case .context:
            ShellColumnWidthPolicy(
                minimum: 300, ideal: 380, maximum: 560, layoutPriority: 1
            )
        }
    }
}
