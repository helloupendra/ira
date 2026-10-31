import AppKit
import SwiftUI
import Testing
@testable import Ira

/// Ira's window and menu bar: the standard menus, editing keys through the Edit menu, and
/// the part of the window shown, kept for the next launch.
@MainActor
@Suite("Ira's window", .serialized)
struct WindowTests {
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

    static func textField(in view: NSView) -> NSTextField? {
        if let field = view as? NSTextField, field.isEditable { return field }
        for child in view.subviews {
            if let found = textField(in: child) { return found }
        }
        return nil
    }

    @Test func theMenuBarHasTheStandardMenus() throws {
        _ = NSApplication.shared
        AppMenu.install()
        let main = try #require(NSApp.mainMenu)
        #expect(main.items.compactMap(\.submenu?.title) == ["Ira", "Edit", "View", "Window", "Help"])
        func item(_ menu: String, _ title: String) -> NSMenuItem? {
            main.items.first { $0.submenu?.title == menu }?.submenu?.items.first { $0.title == title }
        }
        #expect(item("Ira", "Settings…")?.keyEquivalent == ",")
        #expect(item("Ira", "Quit Ira")?.keyEquivalent == "q")
        #expect(item("Ira", "About Ira") != nil)
        #expect(item("Edit", "Paste")?.keyEquivalent == "v")
        #expect(item("Window", "Minimize")?.keyEquivalent == "m")
        #expect(item("Window", "Ira")?.keyEquivalent == "0")
        #expect(NSApp.windowsMenu?.title == "Window" && NSApp.helpMenu?.title == "Help")
    }

    @Test func cmdVPastesIntoTheAskFieldThroughTheEditMenu() throws {
        _ = NSApplication.shared
        AppMenu.install()
        let field = Field()
        let host = NSHostingView(rootView: AskField(field: field))
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 120), styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host
        window.makeKeyAndOrderFront(nil)
        defer { window.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        let ask = try #require(WindowTests.textField(in: host))
        #expect(window.makeFirstResponder(ask))
        // ⌘V is the Edit menu's Paste, whose action reaches the field being typed in. (The
        // menu sends it to the key window, which a test process cannot make key: so it is sent
        // to the field's editor here.)
        let edit = try #require(NSApp.mainMenu?.items.first { $0.submenu?.title == "Edit" }?.submenu)
        let paste = try #require(edit.items.first { $0.keyEquivalent == "v" && $0.keyEquivalentModifierMask == .command })
        try withPasteboard("vo file kahan hai?") {
            let editor = try #require(ask.currentEditor())
            #expect(editor.tryToPerform(try #require(paste.action), with: paste))
            #expect(editor.string == "vo file kahan hai?")
        }
    }

    @Test func thePartShownIsKeptForTheNextLaunch() {
        let key = "windowPane"
        let before = UserDefaults.standard.object(forKey: key)
        defer { UserDefaults.standard.set(before, forKey: key) }
        UserDefaults.standard.removeObject(forKey: key)
        #expect(WindowState().pane == .chat)
        let state = WindowState()
        state.selection = .pane(.settings)
        #expect(WindowState().pane == .settings)
        // One of today's conversations shows in Chat, and is not what opens next time.
        state.selection = .conversation("mac-abc")
        #expect(state.pane == .chat && WindowState().pane == .settings)
    }
}
