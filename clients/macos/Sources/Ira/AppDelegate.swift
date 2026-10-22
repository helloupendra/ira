import AppKit
import Combine
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

    /// Cut, copy, paste, select all, undo: sent to the field being typed in.
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if let action = EditMenu.action(for: event), NSApp.sendAction(action, to: nil, from: self) {
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    /// Stop taking the keyboard, but stay on screen: typing then goes to the app
    /// or the system prompt the person turned to (a password sheet included).
    func giveUpKeyboard() {
        guard isKeyWindow, isVisible else { return }
        orderOut(nil)
        orderFrontRegardless()
    }
}

extension Notification.Name {
    /// Ira is about to open System Settings for a permission: its window steps aside.
    static let iraOpensSystemSettings = Notification.Name("in.ira.mac.opensSystemSettings")
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var model: AppModel!
    private var statusItem: NSStatusItem!
    private var panel: FloatingPanel!
    private var settingsWindow: NSWindow?
    private var hotKey: HotKey?
    private var wakeWatch: Any?
    private var workWatch: Any?
    private var markTimer: Timer?
    private var markFrame = 0
    private var hasSavedFrame = false
    private var observers: [NSObjectProtocol] = []
    private var escapeMonitor: Any?
    /// The window stepped aside for System Settings and comes back after it.
    private var returnAfterSettings = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        ScreenText.noteLaunch()
        model = AppModel()
        IraLog.shared.info("Ira \(IraApp.version) started")

        let root = MainView(model: model, conversation: model.conversation, openSettings: { [weak self] in
            self?.showSettings()
        })
        EditMenu.install()
        panel = FloatingPanel(content: NSHostingView(rootView: root))
        panel.onEscape = { [weak self] in self?.hidePanel() }
        // Where the person left it, and how big.
        hasSavedFrame = UserDefaults.standard.string(forKey: "NSWindow Frame IraPanel") != nil
        panel.setFrameAutosaveName("IraPanel")

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = AppDelegate.menuBarImage()
        statusItem.button?.setAccessibilityLabel("Ira")
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu

        hotKey = HotKey { [weak self] in self?.togglePanel() }
        registerHotKey()
        model.onWake = { [weak self] in self?.showPanel() }
        watchOtherApps()
        // The menu-bar mark: a dot while "Hey Ira" listens, moving bars while Ira works.
        wakeWatch = model.$wakeListening.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateMark() }
        }
        workWatch = model.conversation.$busy.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateMark() }
        }
        model.conversation.onAnswer = { [weak self] text in self?.answered(text) }
        // First launch, or not paired yet: show the window so pairing is the first thing seen.
        if model.screen == .setup {
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
        let remove = NSMenuItem(title: "Remove Ira from this Mac…", action: #selector(removeFromMac), keyEquivalent: "")
        remove.target = self
        menu.addItem(remove)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Ira", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)
    }

    static func describe(_ state: DeviceState, paired: Bool) -> String {
        guard paired else { return "Not paired yet: open Ira to pair this Mac" }
        switch state {
        case .connected(_, let skills):
            return skills.isEmpty
                ? "Connected, with no skills on yet: switch them on in Your devices"
                : "Connected: \(skills.joined(separator: ", "))"
        case .connecting: return "Connecting…"
        case .waiting(let seconds, _): return "Cannot reach your Ira: trying again in \(Int(seconds.rounded())) s"
        case .refused: return "Your Ira no longer knows this Mac: pair it again in Settings"
        case .stopped: return "Not connected"
        }
    }

    @objc func removeFromMac() {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "Remove Ira from this Mac?"
        alert.informativeText = "Your Ira forgets this Mac at once, and the app deletes its key, settings and logs here. Your files are not touched. Then drag Ira from Applications to the Bin."
        alert.addButton(withTitle: "Remove")
        alert.addButton(withTitle: "Cancel")
        alert.buttons.first?.hasDestructiveAction = true
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        Task {
            await model.removeEverything()
            let done = NSAlert()
            done.messageText = "Ira is removed from this Mac"
            done.informativeText = "Drag Ira from Applications to the Bin to finish. To use Ira again, open it and pair it with a new code."
            done.runModal()
            NSApp.terminate(nil)
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
        if !panel.isVisible && !hasSavedFrame {
            hasSavedFrame = true
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

    /// The window never keeps the keyboard from another app or a system prompt:
    /// when anything else becomes active, it lets go. It steps aside entirely
    /// while Ira has System Settings open for a permission, and comes back after.
    private func watchOtherApps() {
        let workspace = NSWorkspace.shared.notificationCenter
        observers.append(workspace.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            guard app?.processIdentifier != getpid() else { return }
            MainActor.assumeIsolated { self?.otherAppActive() }
        })
        observers.append(workspace.addObserver(
            forName: NSWorkspace.didDeactivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            guard app?.bundleIdentifier == "com.apple.systempreferences" else { return }
            MainActor.assumeIsolated { self?.settingsClosed() }
        })
        observers.append(workspace.addObserver(
            forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            guard app?.bundleIdentifier == "com.apple.systempreferences" else { return }
            MainActor.assumeIsolated { self?.settingsClosed() }
        })
        observers.append(NotificationCenter.default.addObserver(
            forName: .iraOpensSystemSettings, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.panel.isVisible else { return }
                self.returnAfterSettings = true
                self.panel.orderOut(nil)
            }
        })
        // While the screen is captured, macOS may ask the person first (monthly on
        // macOS 15 and later): the window drops below such a prompt and lets go
        // of the keyboard, then comes back.
        observers.append(NotificationCenter.default.addObserver(
            forName: ScreenText.capturing, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.panel.isVisible else { return }
                self.panel.level = .normal
                self.panel.giveUpKeyboard()
            }
        })
        observers.append(NotificationCenter.default.addObserver(
            forName: ScreenText.captured, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.panel.level = .floating }
        })
        // Esc closes the window, wherever the cursor is in it.
        escapeMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard event.keyCode == 53, let self, event.window === self.panel else { return event }
            self.hidePanel()
            return nil
        }
    }

    /// Another app (or a system prompt) became active: the window lets go of the
    /// keyboard, and unless it is pinned, gets out of the way. A question still
    /// running carries on; its answer arrives as a notification.
    private func otherAppActive() {
        guard panel.isVisible else { return }
        if model.settings.panelPinned {
            panel.giveUpKeyboard()
        } else {
            panel.orderOut(nil)
        }
    }

    private func answered(_ text: String) {
        guard !panel.isVisible, !text.isEmpty else { return }
        Notifier.post(title: model.assistant, body: text)
    }

    private func updateMark() {
        let working = model.conversation.busy
        if working, markTimer == nil {
            markTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.markFrame = (self.markFrame + 1) % 4
                    self.statusItem.button?.image = AppDelegate.menuBarImage(listening: self.model.wakeListening, frame: self.markFrame)
                }
            }
        } else if !working {
            markTimer?.invalidate()
            markTimer = nil
            markFrame = 0
            statusItem.button?.image = AppDelegate.menuBarImage(listening: model.wakeListening)
        }
        statusItem.button?.toolTip = working ? "Ira is working on your question" : "Ira"
    }

    private func settingsClosed() {
        model.permissions.refresh()
        guard returnAfterSettings else { return }
        returnAfterSettings = false
        // Back, but without the keyboard: the person may be typing elsewhere.
        panel.orderFrontRegardless()
    }

    /// Hide on purpose (Esc, the shortcut): the microphone stops too.
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

    /// The menu-bar mark: the repository's four voice bars, as a template image,
    /// with a dot while "Hey Ira" listens. While Ira works, the bars move
    /// (`frame` 1 to 3).
    static func menuBarImage(listening: Bool = false, frame: Int = 0) -> NSImage {
        let heights: [[CGFloat]] = [[4, 9, 13, 7], [7, 13, 9, 4], [11, 6, 5, 12], [5, 11, 13, 9]]
        let image = NSImage(size: NSSize(width: listening ? 22 : 18, height: 18), flipped: false) { _ in
            NSColor.black.setFill()
            let row = heights[frame % heights.count]
            for (index, height) in row.enumerated() {
                let x = 3 + CGFloat(index) * 3.5
                let rect = NSRect(x: x, y: (18 - height) / 2, width: 2, height: height)
                NSBezierPath(roundedRect: rect, xRadius: 1, yRadius: 1).fill()
            }
            if listening {
                NSBezierPath(ovalIn: NSRect(x: 17.5, y: 13, width: 4, height: 4)).fill()
            }
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = listening ? "Ira, listening for its wake phrase" : "Ira"
        return image
    }
}

extension Notification.Name {
    static let iraFocusInput = Notification.Name("in.ira.mac.focusInput")
}
