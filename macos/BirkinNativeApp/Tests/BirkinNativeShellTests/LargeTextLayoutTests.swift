import AppKit
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Native shell large-text layout")
struct LargeTextLayoutTests {
    @Test("largest accessibility text reflows instead of truncating chrome")
    func layoutPlanAvoidsClipping() {
        let plan = ShellLayoutPlan(
            windowWidth: 960,
            dynamicTypeSize: .accessibility5
        )
        #expect(plan.mode == .panelNavigation)
        #expect(plan.statusAllowsVerticalReflow)
        #expect(plan.columnHeaderLineLimit == nil)
        #expect(plan.columnHeadersUseFixedVerticalSize)
    }

    @MainActor
    @Test("largest accessibility text renders final fixed-window evidence")
    func rendersLargeTextEvidence() throws {
        let store = NativeProjectionStore()
        let view = NativeShellView(
            store: store,
            connectionState: .failed(reason: "Python bridge stopped; reconnect diagnostics are available."),
            initialColumn: .navigation
        )
        .environment(\.dynamicTypeSize, .accessibility5)
        .frame(width: 960, height: 760)
        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:])
        else {
            Issue.record("ImageRenderer did not produce large-text PNG data")
            return
        }
        let output = evidenceDirectory().appendingPathComponent("shell-large-text-final.png")
        try FileManager.default.createDirectory(
            at: output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try png.write(to: output, options: .atomic)
        #expect(png.count > 10_000)
    }

    private func evidenceDirectory() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".omo/evidence/native-shell")
    }
}
