import SwiftUI

public struct ConnectionStatusPill: View {
    public let presentation: ConnectionPresentation
    private let diagnosticsAction: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    public init(
        presentation: ConnectionPresentation,
        diagnosticsAction: @escaping () -> Void = {}
    ) {
        self.presentation = presentation
        self.diagnosticsAction = diagnosticsAction
    }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            content(axis: .horizontal)
            content(axis: .vertical)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(tint.opacity(0.7), lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(presentation.title), \(presentation.transportLabel), \(presentation.detail)"
        )
    }

    @ViewBuilder
    private func content(axis: Axis) -> some View {
        if axis == .horizontal {
            HStack(alignment: .center, spacing: 10) { fields }
        } else {
            VStack(alignment: .leading, spacing: 8) { fields }
        }
    }

    @ViewBuilder
    private var fields: some View {
        Label(presentation.title, systemImage: presentation.symbolName)
            .font(.headline)
            .foregroundStyle(tint)
            .fixedSize(horizontal: false, vertical: true)
        VStack(alignment: .leading, spacing: 1) {
            Text(presentation.transportLabel)
                .font(.subheadline.weight(.semibold))
            Text(presentation.detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .fixedSize(horizontal: false, vertical: true)
        Spacer(minLength: dynamicTypeSize.isAccessibilitySize ? 0 : 8)
        Button(presentation.diagnosticsLabel, action: diagnosticsAction)
            .buttonStyle(DiagnosticsButtonStyle())
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityHint("Opens bounded connection diagnostics")
    }

    private var tint: Color {
        switch presentation.tone {
        case .neutral: .secondary
        case .progress: .blue
        case .healthy: .green
        case .fallback: .orange
        case .warning: .yellow
        case .failure: .red
        }
    }
}

private struct DiagnosticsButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(.primary.opacity(configuration.isPressed ? 0.14 : 0.07))
            .clipShape(Capsule())
    }
}
