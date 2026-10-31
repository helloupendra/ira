import AppKit
import Combine
import IraKit
import SwiftUI

extension Notification.Name {
    /// Ira is about to open System Settings for a permission: its window steps aside.
    static let iraOpensSystemSettings = Notification.Name("in.ira.mac.opensSystemSettings")
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var model: AppModel!
    private var statusItem: NSStatusItem!
    private var main: MainWindowController!
    private var hotKey: HotKey?
    /// ⌃⌥⌘V sends the clipboard to Drop; ⌃⌥⌘C copies the newest item from it.
    private var sendClipboardKey: HotKey?
    private var copyLatestKey: HotKey?
    private var dropTarget: DropTarget?
    private var wakeWatch: Any?
    private var workWatch: Any?
    private var approvalWatch: Any?
    private var markTimer: Timer?
    private var markFrame = 0
    private var observers: [NSObjectProtocol] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        ScreenText.noteLaunch()
        let last = QuitReason.takeLast() ?? "it did not say (it crashed, was force-quit, or the Mac shut down)"
        IraLog.shared.info("Ira \(IraApp.version) started; last time Ira quit because of \(last)")
        model = AppModel()
        AppMenu.install()
        main = MainWindowController(model: model, hotKeyChanged: { [weak self] in self?.registerHotKey() })
        main.onClose = { [weak self] in self?.model.conversation.stopListening() }

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = AppDelegate.menuBarImage()
        statusItem.button?.setAccessibilityLabel("Ira")
        // A shortcut only: a click opens the window; right-click (or Control-click) offers
        // Open Ira and Quit Ira, nothing else.
        statusItem.button?.target = self
        statusItem.button?.action = #selector(statusItemClicked)
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])

        hotKey = HotKey { [weak self] in self?.toggleWindow() }
        registerHotKey()
        sendClipboardKey = HotKey { [weak self] in self?.sendClipboardToDrop() }
        copyLatestKey = HotKey { [weak self] in self?.copyLatestFromDrop() }
        if sendClipboardKey?.register(keyCode: HotKey.sendClipboardKey, modifiers: HotKey.dropModifiers) != true
            || copyLatestKey?.register(keyCode: HotKey.copyLatestKey, modifiers: HotKey.dropModifiers) != true
        {
            IraLog.shared.warning("a Drop hotkey is taken by another app")
        }
        if let button = statusItem.button { dropTarget = DropTarget(drop: model.drop, button: button) }
        Task { await model.drop.refresh() }
        model.onWake = { [weak self] in self?.main.show(.chat) }
        observers.append(NotificationCenter.default.addObserver(forName: .iraShowPanel, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.main.show(.chat) }
        })
        watchPermissions()
        // The menu-bar mark: a dot while "Hey Ira" listens, moving bars while Ira works.
        wakeWatch = model.$wakeListening.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateMark() }
        }
        workWatch = model.conversation.$busy.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateMark() }
        }
        // Orange while an approval lets Ira control this Mac without asking.
        approvalWatch = model.approvals.$now.sink { [weak self] _ in
            DispatchQueue.main.async { self?.updateApprovalMark() }
        }
        model.conversation.onAnswer = { [weak self] text in self?.answered(text) }
        // Opened by the person: the window. Started at login: only the Dock icon and the menu
        // bar, unless this Mac still needs pairing.
        if !AppDelegate.launchedAtLogin() || model.screen != .chat {
            main.show()
        }
    }

    /// Closing the window leaves Ira running: the device connection, the tools and Drop stay up.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// A click on the Dock icon (or opening Ira again) brings the window back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        main.show()
        return true
    }

    /// Whether macOS opened Ira as a login item.
    static func launchedAtLogin() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == kAEOpenApplication
            && event.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
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

    // MARK: The menu-bar icon

    @objc private func statusItemClicked() {
        let event = NSApp.currentEvent
        guard event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true else {
            main.show(.chat)
            return
        }
        statusItem.menu = AppDelegate.statusMenu(hotKey: hotKeyText, target: self)
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }

    /// The icon's menu: Open Ira and Quit Ira.
    static func statusMenu(hotKey: String, target: AnyObject) -> NSMenu {
        let menu = NSMenu()
        let open = NSMenuItem(title: "Open Ira  (\(hotKey))", action: #selector(openPanel), keyEquivalent: "")
        open.target = target
        menu.addItem(open)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Ira", action: #selector(quitFromMenu), keyEquivalent: "q")
        quit.target = target
        menu.addItem(quit)
        return menu
    }

    // MARK: Drop shortcuts

    @objc private func sendClipboardToDrop() {
        let drop = model.drop
        Task { await drop.sendClipboard() }
    }

    @objc private func copyLatestFromDrop() {
        let drop = model.drop
        Task { await drop.copyLatest() }
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
        case .keyUnavailable: return "Ira can't read its key in the Keychain: open Ira and press Try again"
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
            QuitReason.set("Remove Ira from this Mac")
            let done = NSAlert()
            done.messageText = "Ira is removed from this Mac"
            done.informativeText = "Drag Ira from Applications to the Bin to finish. To use Ira again, open it and pair it with a new code."
            done.runModal()
            NSApp.terminate(nil)
        }
    }

    @objc func openPanel() { main.show(.chat) }
    @objc func openSettings() { main.show(.settings) }

    @objc func openHelp() {
        NSWorkspace.shared.open(AppMenu.helpURL)
    }

    // MARK: The window

    /// The shortcut: the window on Chat, ready to type; again, while it is in front, hides Ira.
    func toggleWindow() {
        if NSApp.isActive && main.window.isKeyWindow {
            NSApp.hide(nil)
        } else {
            main.show(.chat)
        }
    }

    /// Permissions can change in System Settings while Ira runs: read them again when it closes,
    /// and when macOS has answered a request.
    private func watchPermissions() {
        let workspace = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.didDeactivateApplicationNotification, NSWorkspace.didTerminateApplicationNotification] {
            observers.append(workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
                guard app?.bundleIdentifier == "com.apple.systempreferences" else { return }
                MainActor.assumeIsolated { self?.model.permissions.refresh() }
            })
        }
        observers.append(NotificationCenter.default.addObserver(
            forName: .iraAskedPermission, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.model.permissions.refresh() }
        })
    }

    // MARK: Quitting, with a reason in the log

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if UserDefaults.standard.string(forKey: QuitReason.key) == nil {
            QuitReason.set(AppDelegate.quitAsker())
        }
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        IraLog.shared.info("Ira quits: \(UserDefaults.standard.string(forKey: QuitReason.key) ?? "no reason given")")
    }

    /// Who asked Ira to quit, when it was not the person through Ira's own menu.
    static func quitAsker() -> String {
        guard let event = NSAppleEventManager.shared().currentAppleEvent,
            event.eventClass == AEEventClass(kCoreEventClass), event.eventID == AEEventID(kAEQuitApplication)
        else { return "a quit from outside Ira's menu" }
        if let pid = event.attributeDescriptor(forKeyword: AEKeyword(keySenderPIDAttr))?.int32Value,
            let app = NSRunningApplication(processIdentifier: pid_t(pid))
        {
            return "a quit request from \(app.localizedName ?? app.bundleIdentifier ?? "process \(pid)") (macOS asks this after a permission change)"
        }
        return "a quit request from macOS (for example after a permission change)"
    }

    @objc func stopApproval() {
        Task { await model.approvals.stop() }
    }

    private func updateApprovalMark() {
        let banner = model.approvals.banner
        statusItem.button?.contentTintColor = banner == nil ? nil : .systemOrange
        if !model.conversation.busy {
            statusItem.button?.toolTip = banner ?? "Ira"
        }
    }

    @objc func quitFromMenu() {
        QuitReason.set("Quit in Ira's menu")
        NSApp.terminate(nil)
    }

    private func answered(_ text: String) {
        guard !(NSApp.isActive && main.isShown), !text.isEmpty else { return }
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
        statusItem.button?.toolTip = working ? "Ira is working on your question" : (model.approvals.banner ?? "Ira")
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
    static let iraShowPanel = Notification.Name("in.ira.mac.showPanel")
}
