import Foundation

/// Every tool this Mac can offer Ira, as the hello lists them: name, description,
/// JSON Schema parameters, skill and tier.
///
/// Tiers (docs/devices.md): 0 reads; 1 small and undoable (open an app, add a
/// note), Ira does it and says so; 2 reaches other people or changes the
/// calendar, so Ira reads it back with its exact target and waits for a yes;
/// 3 needs the PIN. The tier is fixed here; the model cannot lower it. A
/// skill is the grant the person switches on for this Mac with their PIN.
public enum ToolCatalog {
    static func tool(_ name: String, skill: String, tier: Int, _ description: String,
                     properties: [String: JSONValue] = [:], required: [String] = []) -> JSONValue {
        var parameters: [String: JSONValue] = [
            "type": "object", "properties": .object(properties), "additionalProperties": false,
        ]
        if !required.isEmpty { parameters["required"] = .array(required.map { .string($0) }) }
        return [
            "name": .string(name), "description": .string(description), "parameters": .object(parameters),
            "skill": .string(skill), "tier": .number(Double(tier)),
        ]
    }

    static func text(_ description: String) -> JSONValue { ["type": "string", "description": .string(description)] }

    static func integer(_ description: String, _ range: ClosedRange<Int>) -> JSONValue {
        ["type": "integer", "minimum": .number(Double(range.lowerBound)), "maximum": .number(Double(range.upperBound)),
         "description": .string(description)]
    }

    static let date = "A date (2026-10-23) or a local date and time (2026-10-23T14:30)."
    static let maxText = JSONValue.number(Double(Toolbox.maxText))

    // MARK: Files and screen

    public static let files: [JSONValue] = [
        tool("files_find", skill: "files", tier: 0,
             "Find files on this Mac with Spotlight, by words in the name or inside the file, by kind and by date. Returns up to 20: name, folder, path, kind, size and when it was last changed, newest first. Use it for 'where is that file', 'the PDF I downloaded yesterday'.",
             properties: [
                "query": text("Words from the file's name or its text. Leave empty to list recent files of a kind."),
                "kind": ["type": "string", "enum": .array(FileSearch.kinds.keys.sorted().map { .string($0) }), "description": "The kind of file."],
                "modifiedWithinDays": integer("Only files changed or added in the last this many days (1 means the last 24 hours).", 1...3650),
                "folder": text("Look only in this folder: Downloads, Desktop, Documents, or a path such as ~/Projects."),
             ]),
        tool("file_read", skill: "files", tier: 0,
             "Read the text of one file on this Mac: PDF, Word (.docx), RTF, plain text or Markdown, up to 20,000 characters. Give the full path from files_find. Never keychains, ~/Library or hidden files.",
             properties: [
                "path": text("The file's full path, e.g. ~/Downloads/invoice.pdf."),
                "maxChars": ["type": "integer", "minimum": 200, "maximum": maxText, "description": "Read at most this many characters (default and most: 20,000)."],
             ], required: ["path"]),
        tool("file_open", skill: "files", tier: 1,
             "Open a file on this Mac in its usual app. Say that you opened it. Never runs scripts or installers.",
             properties: ["path": text("The file's full path.")], required: ["path"]),
        tool("screen_read", skill: "screen", tier: 0,
             "Read the text of the window in front on this Mac, in any app, only when the person asks what is on their screen. Returns the app's name, the window's title and the text, read on the Mac; no picture is sent."),
    ]

    // MARK: Browsers

    public static let browser: [JSONValue] = [
        tool("browser_tabs", skill: "browser", tier: 0,
             "List the tabs open in the browsers on this Mac (Chrome, Safari, Arc, Edge, Brave): each tab's title and address (without its query), which is in front, and an id. Only titles and addresses, never page contents. Use it for 'what is open in Chrome?'.",
             properties: ["browser": text("Only this browser: chrome, safari, arc, edge or brave.")]),
        tool("browser_show_tab", skill: "browser", tier: 1,
             "Bring one browser tab to the front, by words from its title or address or by its id from browser_tabs. To answer what a tab shows ('how far is that upload?'), bring it to the front, then use screen_read. Say that you switched to it.",
             properties: [
                "match": text("Words from the tab's title or address, e.g. 'upload' or 'github'."),
                "id": text("The tab's id from browser_tabs."),
                "browser": text("Only this browser: chrome, safari, arc, edge or brave."),
             ]),
    ]

    // MARK: People, time and messages

    public static let personal: [JSONValue] = [
        tool("contacts_lookup", skill: "contacts", tier: 0,
             "Look up people in this Mac's Contacts (iCloud, Google and Exchange accounts included) by name, phone number or email. Returns up to 10 with their numbers and emails. Use it to put a name to a number, or to find the number or email to send to.",
             properties: ["query": text("A name, a phone number (any format, or its last digits), or an email address.")], required: ["query"]),
        tool("calendar_read", skill: "calendar", tier: 0,
             "Read the events on this Mac's calendars (iCloud, Google, Exchange): title, start, end, place and calendar. Today by default.",
             properties: [
                "from": text("The first day. \(date) Default: today."),
                "days": integer("How many days from then (default 1).", 1...31),
                "query": text("Only events whose title or place has these words."),
                "calendar": text("Only this calendar, by name."),
             ]),
        tool("calendar_add", skill: "calendar", tier: 2,
             "Add an event to a calendar on this Mac. Give the exact title, start and calendar: they are read back to the person before it is added.",
             properties: [
                "title": text("The event's title."),
                "start": text("When it starts. \(date) A bare date makes an all-day event."),
                "end": text("When it ends. \(date)"),
                "durationMinutes": integer("How long, if no end is given (default 60).", 5...1440),
                "allDay": ["type": "boolean", "description": "An all-day event."],
                "location": text("Where."),
                "notes": text("Notes on the event."),
                "calendar": text("Which calendar, by name. Default: the Mac's default calendar."),
             ], required: ["title", "start"]),
        tool("reminders_list", skill: "reminders", tier: 0,
             "List the reminders on this Mac (Apple Reminders), open ones first by due date.",
             properties: [
                "list": text("Only this list, by name."),
                "includeDone": ["type": "boolean", "description": "Also the ones already done."],
                "query": text("Only reminders whose title has these words."),
             ]),
        tool("reminders_add", skill: "reminders", tier: 1,
             "Add a reminder in Apple Reminders on this Mac, with a due time if given (it alerts then). Say that you added it.",
             properties: [
                "title": text("What to be reminded of."),
                "due": text("When. \(date)"),
                "list": text("Which list, by name. Default: the default list."),
                "notes": text("Notes."),
             ], required: ["title"]),
        tool("reminders_done", skill: "reminders", tier: 1,
             "Mark a reminder as done, by its id from reminders_list or its exact title.",
             properties: ["id": text("The reminder's id."), "title": text("The reminder's exact title.")]),
        tool("mail_search", skill: "mail", tier: 0,
             "Search the Mail app's inbox on this Mac (read only): emails whose subject or sender has these words, from the last days. Returns id, subject, sender, date and whether it was read, newest first.",
             properties: [
                "query": text("Words from the subject or the sender. Empty: the latest emails."),
                "days": integer("How far back, in days (default 14).", 1...365),
                "limit": integer("At most this many (default 10).", 1...25),
             ]),
        tool("mail_read", skill: "mail", tier: 0,
             "Read one email from the Mail app: subject, sender, date, recipients and text, up to 20,000 characters.",
             properties: [
                "id": text("The email's id from mail_search."),
                "maxChars": ["type": "integer", "minimum": 200, "maximum": maxText, "description": "Read at most this many characters."],
             ], required: ["id"]),
        tool("mail_draft", skill: "mail", tier: 2,
             "Write a draft email in the Mail app and open it for the person to check and send. Ira never sends it. Give the exact addresses (look them up with contacts_lookup), subject and body.",
             properties: [
                "to": ["type": "array", "items": ["type": "string"], "description": "Email addresses."],
                "cc": ["type": "array", "items": ["type": "string"], "description": "Email addresses to copy."],
                "subject": text("The subject."),
                "body": text("The text of the email."),
             ], required: ["to"]),
        tool("messages_send", skill: "messages", tier: 2,
             "Send an iMessage from this Mac's Messages app to a phone number or an email address. Give the exact number and the person's name: both are read back before it is sent.",
             properties: [
                "to": text("The phone number (with the country code, e.g. +91...) or email address, from contacts_lookup."),
                "name": text("The person's name, for the read-back."),
                "text": text("The message, exactly as it will be sent."),
             ], required: ["to", "text"]),
        tool("notes_search", skill: "notes", tier: 0,
             "Search Apple Notes on this Mac by words in the title or the text. Returns id, title, folder and when it changed.",
             properties: ["query": text("Words to look for. Empty: the latest notes."), "limit": integer("At most this many (default 10).", 1...25)]),
        tool("notes_read", skill: "notes", tier: 0,
             "Read one note from Apple Notes, up to 20,000 characters.",
             properties: [
                "id": text("The note's id from notes_search."),
                "maxChars": ["type": "integer", "minimum": 200, "maximum": maxText, "description": "Read at most this many characters."],
             ], required: ["id"]),
        tool("notes_add", skill: "notes", tier: 1,
             "Add a note in Apple Notes on this Mac. Say that you added it.",
             properties: ["title": text("The note's title."), "body": text("The note's text."), "folder": text("Which folder, by name.")],
             required: ["title"]),
    ]

    // MARK: Apps

    public static let apps: [JSONValue] = [
        tool("app_open", skill: "apps", tier: 1,
             "Open an app on this Mac by its name (Safari, Calendar, Visual Studio Code...). Say that you opened it.",
             properties: ["name": text("The app's name.")], required: ["name"]),
        tool("url_open", skill: "apps", tier: 2,
             "Open a web page in the person's browser on this Mac. The exact address is read back first.",
             properties: ["url": text("The web address (https://...).")], required: ["url"]),
        tool("vscode_open", skill: "apps", tier: 1,
             "Open a folder or file in VS Code on this Mac, e.g. a repository. With a prompt, the editor's assistant extension opens with it filled in (if this Mac set that up); the person presses Return to send it.",
             properties: ["path": text("The folder's or file's full path, e.g. ~/code/shop."), "prompt": text("A request to fill in for the editor's assistant.")],
             required: ["path"]),
        tool("clipboard_read", skill: "clipboard", tier: 0,
             "Read the text on this Mac's clipboard, only when the person asks about what they copied. Never what a password manager marked as private."),
        tool("shortcuts_list", skill: "shortcuts", tier: 0,
             "List the person's shortcuts in the Shortcuts app on this Mac."),
        tool("shortcuts_run", skill: "shortcuts", tier: 2,
             "Run one of the person's shortcuts by its exact name, with optional text as its input. Shortcuts can do anything the person built them to, so the name and input are read back first.",
             properties: ["name": text("The shortcut's exact name, from shortcuts_list."), "input": text("Text to pass to it.")],
             required: ["name"]),
    ]

    // MARK: Coding tasks

    public static let tasks: [JSONValue] = [
        tool("code_task_start", skill: "tasks", tier: 2,
             "Start a coding task on this Mac: a coding agent works in a new git worktree of one of the person's allowed repositories, on its own branch, with VS Code open on it so they can watch. It never pushes. Ira says when it is done.",
             properties: [
                "repo": text("An allowed repository's name, from code_task_list."),
                "instruction": text("What to do, in full."),
                "openInVSCode": ["type": "boolean", "description": "Open VS Code on the worktree (default: as this Mac is set up)."],
             ], required: ["repo", "instruction"]),
        tool("code_task_status", skill: "tasks", tier: 0,
             "How a coding task is going: running, done, failed or stopped; its latest progress, the files changed and the tests.",
             properties: ["id": text("The task's id.")], required: ["id"]),
        tool("code_task_list", skill: "tasks", tier: 0,
             "This Mac's coding tasks, newest first, and the repositories tasks may use."),
        tool("code_task_stop", skill: "tasks", tier: 1,
             "Stop a running coding task. Its worktree and branch stay.",
             properties: ["id": text("The task's id.")], required: ["id"]),
        tool("code_task_push", skill: "tasks", tier: 3,
             "Push a finished task's own branch to the repository's origin: never main, master or the default branch, never forced, nothing merged. Needs the person's PIN.",
             properties: ["id": text("The task's id.")], required: ["id"]),
    ]

    /// The hello's tools: everything, and the coding tasks only when this Mac has them set up.
    public static func all(tasksConfigured: Bool) -> [JSONValue] {
        files + browser + personal + apps + (tasksConfigured ? tasks : [])
    }
}
