import AppKit
import SwiftUI
import Testing
@testable import Ira

/// The floating window: editing keys reach its fields, and it lets go of the
/// keyboard when another app (or a system prompt) needs it.
@MainActor
@Suite("Ira's window", .serialized)
struct PanelTests {
    final class Field: ObservableObject {
        @Published var text = ""
    }

    struct AskField: View {
        @ObservedObject var field: Field
        var body: some View { TextField("Ask Ira…", text: $field.text).frame(width: 300) }
    }

    /// The general pasteboard, saved and put back, so a test never loses what the person copied.
    func withPasteboard(_ text: String, _ body: () throws -> Void) rethrows {
        let board = NSPasteboard.general
        let saved: [NSPasteboardItem] = (board.pasteboardItems ?? []).map { item in
            let copy = NSPasteboardItem()
            for type in item.types {
                if let data = item.data(forType: type) { copy.setData(data, forType: type) }
            }
            return copy
        }
        defer {
            board.clearContents()
            if !saved.isEmpty { board.writeObjects(saved) }
        }
        board.clearContents()
        board.setString(text, forType: .string)
        try body()
    }

    static func command(_ key: String, keyCode: UInt16, window: NSWindow, shift: Bool = false) -> NSEvent {
        NSEvent.keyEvent(
            with: .keyDown, location: .zero, modifierFlags: shift ? [.command, .shift] : [.command],
            timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber, context: nil,
            characters: key, charactersIgnoringModifiers: key, isARepeat: false, keyCode: keyCode)!
    }

    static func textField(in view: NSView) -> NSTextField? {
        if let field = view as? NSTextField, field.isEditable { return field }
        for child in view.subviews {
            if let found = textField(in: child) { return found }
        }
        return nil
    }

    @Test func cmdVPastesIntoTheAskField() throws {
        _ = NSApplication.shared
        let field = Field()
        let host = NSHostingView(rootView: AskField(field: field))
        let panel = FloatingPanel(content: host)
        panel.makeKeyAndOrderFront(nil)
        defer { panel.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        let ask = try #require(PanelTests.textField(in: host))
        #expect(panel.makeFirstResponder(ask))
        try withPasteboard("vo file kahan hai?") {
            #expect(panel.performKeyEquivalent(with: PanelTests.command("v", keyCode: 9, window: panel)))
            let editor = try #require(ask.currentEditor())
            #expect(editor.string == "vo file kahan hai?")
            // Select all, then copy: the text goes back to the pasteboard.
            #expect(panel.performKeyEquivalent(with: PanelTests.command("a", keyCode: 0, window: panel)))
            NSPasteboard.general.clearContents()
            #expect(panel.performKeyEquivalent(with: PanelTests.command("c", keyCode: 8, window: panel)))
            #expect(NSPasteboard.general.string(forType: .string) == "vo file kahan hai?")
        }
    }

    @Test func editingKeysAreRecognised() {
        _ = NSApplication.shared
        let window = NSWindow()
        #expect(EditMenu.action(for: PanelTests.command("v", keyCode: 9, window: window)) == #selector(NSText.paste(_:)))
        #expect(EditMenu.action(for: PanelTests.command("x", keyCode: 7, window: window)) == #selector(NSText.cut(_:)))
        #expect(EditMenu.action(for: PanelTests.command("z", keyCode: 6, window: window)) == Selector(("undo:")))
        #expect(EditMenu.action(for: PanelTests.command("z", keyCode: 6, window: window, shift: true)) == Selector(("redo:")))
        #expect(EditMenu.action(for: PanelTests.command("q", keyCode: 12, window: window)) == nil)
    }

    @Test func itLetsGoOfTheKeyboard() {
        _ = NSApplication.shared
        let panel = FloatingPanel(content: NSHostingView(rootView: Text("Ira")))
        panel.makeKeyAndOrderFront(nil)
        defer { panel.orderOut(nil) }
        #expect(panel.isKeyWindow)
        panel.giveUpKeyboard()
        #expect(!panel.isKeyWindow)
        #expect(panel.isVisible)
        var closed = false
        panel.onEscape = { closed = true }
        panel.cancelOperation(nil)
        #expect(closed)
    }
}

/// When another app becomes active: hide for an ordinary app, but step below a
/// system prompt, and below anything while Ira asks for a permission.
@Suite("The window and other apps")
struct PanelPolicyTests {
    @Test func anOrdinaryAppHidesIt() {
        #expect(PanelPolicy.onOtherApp(bundleID: "com.google.Chrome", pinned: false, askingPermission: false, capturing: false) == .hide)
        #expect(PanelPolicy.onOtherApp(bundleID: "com.google.Chrome", pinned: true, askingPermission: false, capturing: false) == .letGoOfKeyboard)
    }

    @Test(arguments: ["com.apple.UserNotificationCenter", "com.apple.SecurityAgent", "com.apple.tccd", "com.apple.coreservices.uiagent"])
    func aSystemPromptNeverHidesIt(bundleID: String) {
        #expect(PanelPolicy.onOtherApp(bundleID: bundleID, pinned: false, askingPermission: false, capturing: false) == .stepBelow)
    }

    @Test func aPermissionRequestKeepsIt() {
        // Pressing Allow: whatever comes to the front, the window stays on screen.
        #expect(PanelPolicy.onOtherApp(bundleID: "com.apple.systempreferences", pinned: false, askingPermission: true, capturing: false) == .stepBelow)
        #expect(PanelPolicy.onOtherApp(bundleID: nil, pinned: false, askingPermission: false, capturing: true) == .stepBelow)
    }

    @MainActor
    @Test func steppingBelowKeepsItOnScreen() {
        _ = NSApplication.shared
        let panel = FloatingPanel(content: NSHostingView(rootView: Text("Ira")))
        panel.makeKeyAndOrderFront(nil)
        defer { panel.orderOut(nil) }
        // What the app does for .stepBelow while a permission dialog is up.
        panel.level = .normal
        panel.giveUpKeyboard()
        #expect(panel.isVisible)
        #expect(!panel.isKeyWindow)
        // And when the answer is in.
        panel.level = .floating
        panel.makeKeyAndOrderFront(nil)
        #expect(panel.isKeyWindow)
    }
}
