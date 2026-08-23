import AppKit
import SwiftUI

@MainActor
final class ShellFocusVisibilityView: NSView {
    private var generation: UInt64 = 0
    private var lastReportedGeneration: UInt64?
    private var reportVisible: ((UInt64) -> Void)?
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
        generation: UInt64,
        reportVisible: @escaping (UInt64) -> Void
    ) {
        if self.generation != generation {
            lastReportedGeneration = nil
        }
        self.generation = generation
        self.reportVisible = reportVisible
        observeClipView()
        reportIfVisible()
    }

    override func viewDidMoveToSuperview() {
        super.viewDidMoveToSuperview()
        observeClipView()
        reportIfVisible()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        observeClipView()
        reportIfVisible()
    }

    override func layout() {
        super.layout()
        observeClipView()
        reportIfVisible()
    }

    override func viewWillMove(toSuperview newSuperview: NSView?) {
        if newSuperview == nil, let boundsObserver {
            NotificationCenter.default.removeObserver(boundsObserver)
            self.boundsObserver = nil
            observedClipView = nil
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
            Task { @MainActor in self?.reportIfVisible() }
        }
    }

    private func reportIfVisible() {
        guard lastReportedGeneration != generation,
              isWithinVisibleViewport
        else { return }
        lastReportedGeneration = generation
        reportVisible?(generation)
    }
}

struct ShellFocusVisibilityProbe: NSViewRepresentable {
    let generation: UInt64
    let reportVisible: (UInt64) -> Void

    func makeNSView(context _: Context) -> ShellFocusVisibilityView {
        let view = ShellFocusVisibilityView()
        view.configure(generation: generation, reportVisible: reportVisible)
        return view
    }

    func updateNSView(
        _ view: ShellFocusVisibilityView,
        context _: Context
    ) {
        view.configure(generation: generation, reportVisible: reportVisible)
    }
}
