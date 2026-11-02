import AppKit
import IraKit

/// Ira's window drawn into PNGs, for docs and reviews: `IRA_SNAPSHOT=<folder> Ira` draws each
/// part of the window in light and dark, then closes it and opens it again (as a click on the
/// Dock icon does) for one more, and quits. Nothing shows on screen and Ira never becomes the
/// app in front: no Dock icon, and the window is fully transparent and lets clicks through.
@MainActor
enum Snapshot {
    /// A snapshot run asks macOS for nothing: no permission, no notification, no microphone,
    /// so the test build never appears in System Settings' lists.
    nonisolated static let active = !(ProcessInfo.processInfo.environment["IRA_SNAPSHOT"] ?? "").isEmpty

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
        // A conversation with receipts and an action waiting, then listening, from sample lines.
        main.state.selection = .pane(.chat)
        model.conversation.entries = sample
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("chat-conversation-\(dark ? "dark" : "light").png"))
        }
        // A long conversation, scrolled to its end: the header must stay clear of what scrolls under it.
        model.conversation.entries = sample + longer
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("chat-long-\(dark ? "dark" : "light").png"))
        }
        // At the narrowest the window goes: nothing in the header truncates or overlaps.
        let wide = main.window.frame
        main.window.setContentSize(main.window.minSize)
        wait(1)
        save(main.window, to: folder.appendingPathComponent("chat-narrow-dark.png"))
        main.window.setFrame(wide, display: false)
        model.conversation.entries = sample
        model.conversation.listening = true
        model.conversation.caption = "Remind me at six to send the invoice to Sunrise Dental Clinic"
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("listening-\(dark ? "dark" : "light").png"))
        }
        // Ira saying an answer: a short one, one that fills the window, and one too long for it.
        model.conversation.caption = ""
        model.conversation.mode = .speaking
        let answers = [
            ("short", "सनराइज़ डेंटल क्लिनिक में कल दो appointments हैं।"),
            ("medium", String(repeating: "कल सनराइज़ डेंटल क्लिनिक में दो appointments हैं, पहली सुबह 10:30 बजे और दूसरी दोपहर 3 बजे। ", count: 4)),
            ("long", String(repeating: "कल सनराइज़ डेंटल क्लिनिक में दो appointments हैं, पहली सुबह 10:30 बजे और दूसरी दोपहर 3 बजे। ", count: 16)),
        ]
        for (name, answer) in answers {
            model.conversation.entries = sample + [Entry(role: .ira, text: answer)]
            for dark in [false, true] {
                main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                wait(1)
                save(main.window, to: folder.appendingPathComponent("speaking-\(name)-\(dark ? "dark" : "light").png"))
            }
        }
        // Listening to a microphone that gives nothing.
        model.conversation.caption = ""
        model.conversation.micName = AudioIO.inputName
        model.conversation.micSilent = true
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("listening-silent-\(dark ? "dark" : "light").png"))
        }
        model.conversation.micSilent = false
        // Working on a question: THINKING with the step in words, then the same with the
        // microphone still open, then the chat's row with a tool done so far.
        let conversation = model.conversation
        conversation.entries = sample + [Entry(role: .you, text: "Which AI session is running on my Mac?")]
        conversation.busy = true
        conversation.askedAt = Date().addingTimeInterval(-5)
        conversation.step = Conversation.phrase("ai_sessions")
        for (name, mode) in [("listening-thinking", Conversation.Mode.thinking), ("listening-still", .listening)] {
            conversation.mode = mode
            for dark in [false, true] {
                main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                wait(1)
                save(main.window, to: folder.appendingPathComponent("\(name)-\(dark ? "dark" : "light").png"))
            }
        }
        conversation.listening = false
        conversation.mode = .thinking
        conversation.step = Conversation.phrase("web_search")
        conversation.stepsDone = [Receipts.line("ai_sessions", seconds: 0.8)]
        for dark in [false, true] {
            main.window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            wait(1)
            save(main.window, to: folder.appendingPathComponent("chat-thinking-\(dark ? "dark" : "light").png"))
        }
        conversation.busy = false
        conversation.stepsDone = []
        conversation.mode = .idle
        model.conversation.listening = false
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

    /// A short conversation to draw: a question, an answer with its receipts, and an action
    /// waiting for the PIN.
    /// More of a day's questions, with **markdown** in the answers as models write it.
    private static var longer: [Entry] {
        [
            Entry(role: .you, text: "What is on my calendar tomorrow?"),
            Entry(role: .ira, text: "Tomorrow:\n- **10:00** cleaning at Sunrise Dental Clinic\n- **12:30** lunch with the supplier\n- **4:00** call about the invoice"),
            Entry(role: .you, text: "Which tab has the clinic's booking page?"),
            Entry(role: .ira, text: "The tab **\"Booking - Sunrise Dental Clinic\"** in Chrome. Run `make test` before you change the form."),
            Entry(role: .you, text: "Remind me to call them at four"),
            Entry(role: .ira, text: "Done: a reminder at 4:00 PM to call Sunrise Dental Clinic."),
        ]
    }

    private static var sample: [Entry] {
        var answer = Entry(
            role: .ira,
            text: "It is Invoice-INV-7.pdf in your Downloads, from yesterday at 4:04 PM: the signed copy for Sunrise Dental Clinic. Shall I email it to them?")
        answer.receipts = ["files find · 0.4 s", "file read · 1.1 s"]
        let action = PendingAction(id: "snapshot", summary: "Email Invoice-INV-7.pdf to Sunrise Dental Clinic", tier: 3, status: "pending")
        return [
            Entry(role: .you, text: "vo PDF kahan hai jo kal download kiya?"),
            answer,
            Entry(role: .you, text: "haan, bhej do"),
            Entry(role: .note, text: action.summary, action: action),
        ]
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
