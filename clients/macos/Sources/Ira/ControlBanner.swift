import AppKit
import Combine
import IraKit
import SwiftUI

/// While Ira may control this Mac, a small bar stays over everything, on every desktop, with Stop:
/// whichever app is in front, it is never hidden, and it never takes the keyboard from it.
@MainActor
final class ControlBanner {
    private let approvals: ApprovalMonitor
    private var panel: NSPanel?
    private var watching: AnyCancellable?

    init(approvals: ApprovalMonitor) {
        self.approvals = approvals
        watching = approvals.objectWillChange.sink { [weak self] _ in
            DispatchQueue.main.async { self?.update() }
        }
    }

    private func update() {
        guard !Snapshot.active else { return }
        if approvals.banner == nil {
            panel?.orderOut(nil)
            return
        }
        let panel = panel ?? make()
        self.panel = panel
        if !panel.isVisible {
            place(panel)
            panel.orderFrontRegardless()
        }
    }

    private func make() -> NSPanel {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 44),
            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.contentView = NSHostingView(rootView: ControlBannerView(approvals: approvals))
        return panel
    }

    private func place(_ panel: NSPanel) {
        guard let screen = NSScreen.main else { return }
        let area = screen.visibleFrame
        panel.setFrameOrigin(NSPoint(x: area.midX - panel.frame.width / 2, y: area.maxY - panel.frame.height - 8))
    }
}

struct ControlBannerView: View {
    @ObservedObject var approvals: ApprovalMonitor
    /// What it says in a picture, with no window open.
    var shown: String?

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(Color.orange).frame(width: 9, height: 9)
            Text(shown ?? approvals.banner ?? "")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.white)
                .lineLimit(1)
            Spacer(minLength: 8)
            Button("Stop") { Task { await approvals.stop() } }
                .keyboardShortcut(.cancelAction)
                .help("Ira stops now. The next step on this Mac asks for your PIN again.")
        }
        .padding(.horizontal, 14)
        .frame(width: 420, height: 44)
        .background(Color.black.opacity(0.86), in: Capsule())
    }
}
