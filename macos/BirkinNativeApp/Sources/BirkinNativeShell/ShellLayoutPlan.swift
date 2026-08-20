import SwiftUI

public enum ShellLayoutMode: Equatable, Sendable {
    case threeColumns
    case panelNavigation
}

public struct ShellLayoutPlan: Equatable, Sendable {
    public let mode: ShellLayoutMode
    public let statusAllowsVerticalReflow: Bool
    public let columnHeaderLineLimit: Int?
    public let columnHeadersUseFixedVerticalSize: Bool
    public let columnsScrollIndependently: Bool

    public init(windowWidth: CGFloat, dynamicTypeSize: DynamicTypeSize) {
        mode = dynamicTypeSize.isAccessibilitySize || windowWidth < 900
            ? .panelNavigation
            : .threeColumns
        statusAllowsVerticalReflow = true
        columnHeaderLineLimit = nil
        columnHeadersUseFixedVerticalSize = true
        columnsScrollIndependently = true
    }
}
