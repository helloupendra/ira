import AppKit
import IraKit
import SwiftUI

/// A borderless panel that can take typing without bringing Ira to the front,
/// so the app you were using stays "the window in front" for screen reading.
final class FloatingPanel: NSPanel {
    var onEscape: (() -> Void)?

    init(content: NSView) {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 560),
            styleMask: [.titled, .closable, .resizable, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered, defer: false)
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hidesOnDeactivate = false
        isReleasedWhenClosed = false
        minSize = NSSize(width: 340, height: 420)
        contentView = content
        standardWindowButton(.miniaturizeButton)?.isHidden = true
        standardWindowButton(.zoomButton)?.isHidden = true
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func cancelOperation(_ sender: Any?) {
        onEscape?()
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var model: AppModel!
    private var statusItem: NSStatusItem!
    private var panel: FloatingPanel!
    private var settingsWindow: NSWindow?
    private var hotKey: HotKey?

    func applicationDidFinishLaunching(_ notification: Notification) {
        model = AppModel()
        IraLog.shared.info("Ira \(IraApp.version) started")

        let root = MainView(model: model, conversation: model.conversation, openSettings: { [weak self] in
            self?.showSettings()
        })
        panel = FloatingPanel(content: NSHostingView(rootView: root))
        panel.onEscape = { [weak self] in self?.hidePanel() }

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = AppDelegate.menuBarImage()
        statusItem.button?.setAccessibilityLabel("Ira")
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        hotKey = HotKey { [weak self] in self?.togglePanel() }
        registerHotKey()
        // First launch, or not paired yet: show the window so pairing is the first thing seen.
        if !model.paired || !model.settings.firstRunDone {
            showPanel()
        }
    }

    func registerHotKey() {
        let settings = model.settings
        if hotKey?.register(keyCode: settings.hotKeyCode, modifiers: settings.hotKeyModifiers) != true {
            IraLog.shared.warning("the hotkey is taken by another app")
        }
    }

    var hotKeyText: String {
        HotKey.describe(keyCode: model.settings.hotKeyCode, modifiers: model.settings.hotKeyModifiers)
    }

    // MARK: The menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let open = NSMenuItem(title: "Open \(model.assistant)  (\(hotKeyText))", action: #selector(openPanel), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        let state = NSMenuItem(title: AppDelegate.describe(model.deviceState, paired: model.paired), action: nil, keyEquivalent: "")
        state.isEnabled = false
        menu.addItem(state)
        menu.addItem(.separator())
        if !model.activity.isEmpty {
            let header = NSMenuItem(title: "What I read", action: nil, keyEquivalent: "")
            header.isEnabled = false
            menu.addItem(header)
            for entry in model.activity.prefix(5) {
                let item = NSMenuItem(title: "\(entry.verb): \(entry.target)", action: nil, keyEquivalent: "")
                item.isEnabled = false
                menu.addItem(item)
            }
            menu.addItem(.separator())
        }
        let settings = NSMenuItem(title: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
        settings.target = self
        menu.addItem(settings)
        let logs = NSMenuItem(title: "Show Logs", action: #selector(openLogs), keyEquivalent: "")
        logs.target = self
        menu.addItem(logs)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Ira", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)
    }

    static func describe(_ state: DeviceState, paired: Bool) -> String {
        guard paired else { return "Not paired yet" }
        switch state {
        case .connected(_, let skills):
            return skills.isEmpty ? "Connected: no skills on yet" : "Connected: \(skills.joined(separator: ", "))"
        case .connecting: return "Connecting…"
        case .waiting(let seconds, _): return "Offline: trying again in \(Int(seconds.rounded())) s"
        case .refused: return "This Mac was removed from Ira: pair it again"
        case .stopped: return "Not connected"
        }
    }

    @objc func openPanel() { showPanel() }
    @objc func openSettings() { showSettings() }

    @objc func openLogs() {
        if let directory = IraLog.defaultDirectory {
            NSWorkspace.shared.open(directory)
        }
    }

    // MARK: The window

    func togglePanel() {
        panel.isVisible ? hidePanel() : showPanel()
    }

    func showPanel() {
        if !panel.isVisible {
            let mouse = NSEvent.mouseLocation
            let screen = NSScreen.screens.first(where: { $0.frame.contains(mouse) }) ?? NSScreen.main
            if let frame = screen?.visibleFrame {
                let size = panel.frame.size
                panel.setFrameOrigin(NSPoint(x: frame.midX - size.width / 2, y: frame.maxY - size.height - 40))
            }
        }
        panel.makeKeyAndOrderFront(nil)
        NotificationCenter.default.post(name: .iraFocusInput, object: nil)
    }

    func hidePanel() {
        panel.orderOut(nil)
        model.conversation.stopListening()
    }

    func showSettings() {
        if settingsWindow == nil {
            let view = SettingsView(model: model, conversation: model.conversation, hotKeyChanged: { [weak self] in
                self?.registerHotKey()
            })
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 520, height: 600),
                styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            window.title = "Ira Settings"
            window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: view)
            window.center()
            settingsWindow = window
        }
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow?.makeKeyAndOrderFront(nil)
    }

    /// The menu-bar mark: the repository's four voice bars, as a template image.
    static func menuBarImage() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            NSColor.black.setFill()
            let bars: [(x: CGFloat, y: CGFloat, h: CGFloat)] = [(3, 7, 4), (6.5, 4.5, 9), (10, 2.5, 13), (13.5, 5.5, 7)]
            for bar in bars {
                NSBezierPath(roundedRect: NSRect(x: bar.x, y: bar.y, width: 2, height: bar.h), xRadius: 1, yRadius: 1).fill()
            }
            _ = rect
            return true
        }
        image.isTemplate = true
        return image
    }
}

extension Notification.Name {
    static let iraFocusInput = Notification.Name("in.ira.mac.focusInput")
}
