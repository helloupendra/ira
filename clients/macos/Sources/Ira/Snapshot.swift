import AppKit
import IraKit

/// Ira's window drawn into PNGs, for docs and reviews: `IRA_SNAPSHOT=<folder> Ira` draws each
/// part of the window in light and dark, then closes it and opens it again (as a click on the
/// Dock icon does) for one more, and quits. Nothing shows on screen and Ira never becomes the
/// app in front: no Dock icon, and the window is fully transparent and lets clicks through.
@MainActor
enum Snapshot {
    static func run(into folder: URL) {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let model = AppModel()
        let main = MainWindowController(model: model, hotKeyChanged: {})
        main.window.alphaValue = 0
        main.window.ignoresMouseEvents = true
        main.window.orderFrontRegardless()
        // Time for the device connection and today's conversations to arrive; then the
        // earliest of today's is opened, so Chat shows one.
        wait(4)
        if let earliest = model.conversation.today.last {
            Task { await model.conversation.open(earliest.id) }
            wait(2)
        }
        for pane in Pane.allCases {
            for dark in [false, true] {
                main.state.selection = .pane(pane)
                main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                wait(1)
                save(main.window, to: folder.appendingPathComponent("\(pane.rawValue)-\(dark ? "dark" : "light").png"))
            }
        }
        // A new conversation: what an empty Chat says.
        model.conversation.clear()
        main.state.selection = .pane(.chat)
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("chat-new-\(dark ? "dark" : "light").png"))
        }
        main.window.appearance = nil
        main.window.performClose(nil)
        wait(1)
        print("after closing: Ira running, window shown \(main.window.isVisible)")
        main.show()  // what a click on the Dock icon does
        wait(1)
        print("after reopening: window shown \(main.window.isVisible)")
        save(main.window, to: folder.appendingPathComponent("reopened.png"))
        exit(0)
    }

    private static func wait(_ seconds: TimeInterval) {
        RunLoop.main.run(until: Date().addingTimeInterval(seconds))
    }

    /// The whole window, title bar and toolbar included.
    private static func save(_ window: NSWindow, to file: URL) {
        guard let frame = window.contentView?.superview else { return }
        frame.layoutSubtreeIfNeeded()
        guard let bitmap = frame.bitmapImageRepForCachingDisplay(in: frame.bounds) else { return }
        frame.cacheDisplay(in: frame.bounds, to: bitmap)
        try? bitmap.representation(using: .png, properties: [:])?.write(to: file)
        print("saved \(file.lastPathComponent)")
    }
}
