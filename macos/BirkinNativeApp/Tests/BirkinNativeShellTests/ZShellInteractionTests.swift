import AppKit
import SwiftUI
import Testing

@testable import BirkinNativeProtocol
@testable import BirkinNativeShell

@Suite("Production shell interactions")
struct ShellInteractionTests {
    @MainActor private static let appDelegate = ShellInteractionAppDelegate()
    @MainActor private static var retainedPanels: [NSPanel] = []

    @MainActor
    @Test("production split dragging and keyboard shortcuts invoke real shell actions")
    func productionShellInteractions() throws {
        NSApplication.shared.delegate = Self.appDelegate
        var widths: [ShellColumnID: CGFloat] = [:]
        let model = ShellPresentationModel()
        let hostingView = NSHostingView(rootView: NativeShellView(
            store: NativeProjectionStore(),
            connectionState: .disconnected,
            columnWidthAction: { widths[$0] = $1 },
            presentationModel: model
        ))
        let window = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 1_280, height: 760),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.contentView = hostingView
        Self.retainedPanels.append(window)
        window.makeKeyAndOrderFront(nil)
        hostingView.layoutSubtreeIfNeeded()

        let initialWidth = try #require(widths[.navigation])
        let policy = ShellLayoutPlan(
            windowWidth: 1_280,
            dynamicTypeSize: .large
        ).width(for: .navigation)

        try dragDivider(from: initialWidth, to: 20, in: window)
        hostingView.layoutSubtreeIfNeeded()
        #expect(widths[.navigation, default: 0] >= policy.minimum - 1)

        let clampedMinimum = try #require(widths[.navigation])
        try dragDivider(from: clampedMinimum, to: 1_000, in: window)
        hostingView.layoutSubtreeIfNeeded()
        #expect(widths[.navigation, default: 0] <= policy.maximum + 1)
        #expect(widths[.navigation] != initialWidth)

        try sendKey("2", keyCode: 19, modifiers: .command, to: window)
        #expect(model.target == .section(.conversation))
        try sendKey("3", keyCode: 20, modifiers: .command, to: window)
        #expect(model.target == .section(.approvals))
        try sendKey("1", keyCode: 18, modifiers: .command, to: window)
        #expect(model.target == .section(.sessions))
        try sendKey("a", keyCode: 0, modifiers: [.command, .shift], to: window)
        #expect(model.target == .section(.approvals))

        let escape = ShellKeyboardModel.commands.first { $0.shortcut == "escape" }
        #expect(escape?.binding == .nativeSystem)
    }

    @MainActor
    private func sendKey(
        _ character: String,
        keyCode: UInt16,
        modifiers: NSEvent.ModifierFlags,
        to window: NSWindow
    ) throws {
        let event = try #require(NSEvent.keyEvent(
            with: .keyDown,
            location: .zero,
            modifierFlags: modifiers,
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber,
            context: nil,
            characters: character,
            charactersIgnoringModifiers: character,
            isARepeat: false,
            keyCode: keyCode
        ))
        #expect(window.performKeyEquivalent(with: event))
    }

    @MainActor
    private func dragDivider(from startX: CGFloat, to endX: CGFloat, in window: NSWindow) throws {
        func mouseEvent(_ type: NSEvent.EventType, x: CGFloat) throws -> NSEvent {
            try #require(NSEvent.mouseEvent(
                with: type,
                location: NSPoint(x: x, y: 320),
                modifierFlags: [],
                timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: window.windowNumber,
                context: nil,
                eventNumber: 0,
                clickCount: 1,
                pressure: type == .leftMouseUp ? 0 : 1
            ))
        }

        let mouseDown = try mouseEvent(.leftMouseDown, x: startX)
        let mouseDragged = try mouseEvent(.leftMouseDragged, x: endX)
        let mouseUp = try mouseEvent(.leftMouseUp, x: endX)
        NSApp.postEvent(mouseUp, atStart: true)
        NSApp.postEvent(mouseDragged, atStart: true)
        window.sendEvent(mouseDown)
    }
}

private final class ShellInteractionAppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        false
    }
}
