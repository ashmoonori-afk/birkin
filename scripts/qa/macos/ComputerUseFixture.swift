import AppKit
import Foundation

final class FixtureController: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var counterLabel: NSTextField!
    private var valueField: NSTextField!
    private var incrementButton: NSButton!
    private var counter = 0
    private var emittedReady = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let title = ProcessInfo.processInfo.environment[
            "BIRKIN_CU_FIXTURE_TITLE"
        ] ?? "Birkin Computer Use QA Fixture"
        window = NSWindow(
            contentRect: NSRect(x: 160, y: 160, width: 560, height: 420),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = title
        window.setFrameAutosaveName("")

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 14
        root.edgeInsets = NSEdgeInsets(
            top: 24,
            left: 24,
            bottom: 24,
            right: 24
        )

        let heading = NSTextField(labelWithString: "Birkin Computer Use QA")
        heading.font = NSFont.systemFont(ofSize: 24, weight: .semibold)
        heading.setAccessibilityIdentifier("fixture.heading")
        root.addArrangedSubview(heading)

        valueField = NSTextField(string: "before")
        valueField.placeholderString = "Synthetic value"
        valueField.setAccessibilityIdentifier("fixture.value")
        valueField.widthAnchor.constraint(equalToConstant: 360).isActive = true
        root.addArrangedSubview(valueField)

        incrementButton = NSButton(
            title: "Increment synthetic counter",
            target: self,
            action: #selector(incrementCounter)
        )
        incrementButton.bezelStyle = .rounded
        incrementButton.setAccessibilityIdentifier("fixture.increment")
        root.addArrangedSubview(incrementButton)

        counterLabel = NSTextField(labelWithString: "count=0")
        counterLabel.setAccessibilityIdentifier("fixture.counter")
        root.addArrangedSubview(counterLabel)

        let slider = NSSlider(
            value: 0.25,
            minValue: 0,
            maxValue: 1,
            target: nil,
            action: nil
        )
        slider.setAccessibilityIdentifier("fixture.slider")
        slider.widthAnchor.constraint(equalToConstant: 360).isActive = true
        root.addArrangedSubview(slider)

        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.setAccessibilityIdentifier("fixture.scroll")
        let document = NSTextView(
            frame: NSRect(x: 0, y: 0, width: 480, height: 520)
        )
        document.string = (1...30)
            .map { "Synthetic row \($0)" }
            .joined(separator: "\n")
        document.isEditable = false
        scrollView.documentView = document
        scrollView.widthAnchor.constraint(equalToConstant: 480).isActive = true
        scrollView.heightAnchor.constraint(equalToConstant: 180).isActive = true
        root.addArrangedSubview(scrollView)

        window.contentView = root
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        guard !emittedReady else { return }
        emittedReady = true
        let ready: [String: Any] = [
            "event": "fixture.ready",
            "pid": ProcessInfo.processInfo.processIdentifier,
            "window_title": window.title,
            "counter": counterLabel.stringValue,
            "application_active": NSApp.isActive,
            "window_key": window.isKeyWindow,
            "window_visible": window.isVisible,
        ]
        let payload = try! JSONSerialization.data(
            withJSONObject: ready,
            options: [.sortedKeys]
        )
        print(String(data: payload, encoding: .utf8)!)
        fflush(stdout)
    }

    @objc private func incrementCounter() {
        counter += 1
        counterLabel.stringValue = "count=\(counter)"
        incrementButton.title = "Increment synthetic counter (\(counter))"
    }

    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        true
    }
}

let application = NSApplication.shared
let controller = FixtureController()
application.setActivationPolicy(.regular)
application.delegate = controller
application.run()
