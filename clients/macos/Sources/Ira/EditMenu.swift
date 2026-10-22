import AppKit

/// Copy, paste and the other editing keys.
///
/// A menu-bar app has no menu bar of its own, so Cmd-C, Cmd-V, Cmd-X, Cmd-A and
/// Cmd-Z reach no one. Ira installs a standard main menu (never shown while it
/// runs as a menu-bar app, but it carries the key equivalents for its Settings
/// window), and its floating window sends the same actions itself, since it
/// takes typing without making Ira the active app.
enum EditMenu {
    @MainActor
    static func install() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "Ira")
        appMenu.addItem(withTitle: "Quit Ira", action: #selector(AppDelegate.quitFromMenu), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        NSApp.mainMenu = main
    }

    /// The editing action a key press means, or nil: Cmd-X, C, V, A, Z and Shift-Cmd-Z.
    static func action(for event: NSEvent) -> Selector? {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        guard event.type == .keyDown, flags.contains(.command), !flags.contains(.control), !flags.contains(.option)
        else { return nil }
        switch event.charactersIgnoringModifiers?.lowercased() {
        case "x": return #selector(NSText.cut(_:))
        case "c": return #selector(NSText.copy(_:))
        case "v": return #selector(NSText.paste(_:))
        case "a": return #selector(NSText.selectAll(_:))
        case "z": return flags.contains(.shift) ? Selector(("redo:")) : Selector(("undo:"))
        default: return nil
        }
    }
}
