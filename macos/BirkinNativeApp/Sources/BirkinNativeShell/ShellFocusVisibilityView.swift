import AppKit
import SwiftUI

@MainActor
final class ShellFocusVisibilityView: NSView {
    private var lastReportedVisibility: Bool?
    private var reportVisibility: ((Bool) -> Void)?
    private weak var observedClipView: NSClipView?
    private var boundsObserver: NSObjectProtocol?

    var isWithinVisibleViewport: Bool {
        guard !isHidden, alphaValue > 0 else { return false }
        let intersection = bounds.intersection(visibleRect)
        return !intersection.isNull
            && intersection.width > 0
            && intersection.height > 0
    }

    func configure(
        reportVisibility: @escaping (Bool) -> Void
    ) {
        self.reportVisibility = reportVisibility
        observeClipView()
        reportCurrentVisibility()
    }

    override func viewDidMoveToSuperview() {
        super.viewDidMoveToSuperview()
        observeClipView()
        reportCurrentVisibility()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        observeClipView()
        reportCurrentVisibility()
    }

    override func layout() {
        super.layout()
        observeClipView()
        reportCurrentVisibility()
    }

    override func viewWillMove(toSuperview newSuperview: NSView?) {
        if newSuperview == nil, let boundsObserver {
            NotificationCenter.default.removeObserver(boundsObserver)
            self.boundsObserver = nil
            observedClipView = nil
            lastReportedVisibility = false
            reportVisibility?(false)
        }
        super.viewWillMove(toSuperview: newSuperview)
    }

    private func observeClipView() {
        let clipView = enclosingScrollView?.contentView
        guard observedClipView !== clipView else { return }
        if let boundsObserver {
            NotificationCenter.default.removeObserver(boundsObserver)
        }
        boundsObserver = nil
        observedClipView = clipView
        guard let clipView else { return }
        clipView.postsBoundsChangedNotifications = true
        boundsObserver = NotificationCenter.default.addObserver(
            forName: NSView.boundsDidChangeNotification,
            object: clipView,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.reportCurrentVisibility() }
        }
    }

    private func reportCurrentVisibility() {
        let isVisible = isWithinVisibleViewport
        guard lastReportedVisibility != isVisible else { return }
        lastReportedVisibility = isVisible
        reportVisibility?(isVisible)
    }
}

struct ShellFocusVisibilityProbe: NSViewRepresentable {
    let reportVisibility: (Bool) -> Void

    func makeNSView(context _: Context) -> ShellFocusVisibilityView {
        let view = ShellFocusVisibilityView()
        view.configure(reportVisibility: reportVisibility)
        return view
    }

    func updateNSView(
        _ view: ShellFocusVisibilityView,
        context _: Context
    ) {
        view.configure(reportVisibility: reportVisibility)
    }
}
