import AppKit
import Foundation

/// One thing Ira used on this Mac, for the "What I read" list: never what it read.
public struct Activity: Equatable, Identifiable, Sendable {
    public let id = UUID()
    public let at: Date
    public let tool: String
    /// A path, a search, or the app and window read: names, never contents.
    public let target: String
    public let ok: Bool

    public init(at: Date = Date(), tool: String, target: String, ok: Bool) {
        self.at = at
        self.tool = tool
        self.target = target
        self.ok = ok
    }

    public static func == (a: Activity, b: Activity) -> Bool {
        a.at == b.at && a.tool == b.tool && a.target == b.target && a.ok == b.ok
    }

    /// What the tool did, in words.
    public var verb: String {
        switch tool {
        case "files_find": return "Looked for files"
        case "file_read": return "Read a file"
        case "file_open": return "Opened a file"
        case "screen_read": return "Read your screen"
        case "browser_tabs": return "Listed your browser tabs"
        case "browser_show_tab": return "Switched to a tab"
        case "contacts_lookup": return "Looked up a contact"
        case "calendar_read": return "Read your calendar"
        case "calendar_add": return "Added an event"
        case "reminders_list": return "Read your reminders"
        case "reminders_add": return "Added a reminder"
        case "reminders_done": return "Completed a reminder"
        case "mail_search": return "Searched your mail"
        case "mail_read": return "Read an email"
        case "mail_draft": return "Drafted an email"
        case "messages_send": return "Sent a message"
        case "notes_search": return "Searched your notes"
        case "notes_read": return "Read a note"
        case "notes_add": return "Added a note"
        case "app_open": return "Opened an app"
        case "url_open": return "Opened a web page"
        case "vscode_open": return "Opened VS Code"
        case "clipboard_read": return "Read the clipboard"
        case "shortcuts_list": return "Listed your shortcuts"
        case "shortcuts_run": return "Ran a shortcut"
        case "code_task_start": return "Started a coding task"
        case "code_task_status": return "Checked a coding task"
        case "code_task_list": return "Listed coding tasks"
        case "code_task_stop": return "Stopped a coding task"
        case "code_task_push": return "Pushed a task's branch"
        default: return tool
        }
    }
}

/// The tools this Mac offers Ira (`ToolCatalog` lists them with their skills and
/// tiers), and the "What I read" record of each call.
///
/// Everything a tool returns reaches the model marked untrusted by the server:
/// it is data, never instructions.
public final class Toolbox: ToolRunner, @unchecked Sendable {
    public static let maxText = 20_000

    public typealias FrontApp = @Sendable () async -> (pid: pid_t, name: String)?
    public typealias Opener = @Sendable (URL) async -> Bool

    private let policy: @Sendable () -> PathPolicy
    private let frontApp: FrontApp
    private let opener: Opener
    private let record: @Sendable (Activity) -> Void
    private let log: IraLog
    private let eventKit = EventKitTools()
    /// Coding tasks; their done and failed events go out through `announce`.
    public let tasks: CodeTasks

    public init(
        policy: @escaping @Sendable () -> PathPolicy,
        frontApp: @escaping FrontApp,
        opener: @escaping Opener = Toolbox.workspaceOpen,
        tasks: CodeTasks = CodeTasks(),
        log: IraLog = .shared,
        record: @escaping @Sendable (Activity) -> Void
    ) {
        self.policy = policy
        self.frontApp = frontApp
        self.opener = opener
        self.tasks = tasks
        self.log = log
        self.record = record
    }

    public static let workspaceOpen: Opener = { url in
        await MainActor.run { NSWorkspace.shared.open(url) }
    }

    // MARK: The hello

    /// The tools for the hello: everything, and coding tasks when this Mac has them set up.
    public var definitions: [JSONValue] { ToolCatalog.all(tasksConfigured: tasks.configured) }

    /// The files and screen tools (the first four), as the original hello listed them.
    public static var definitions: [JSONValue] { ToolCatalog.files }

    // MARK: Calls

    /// Called when macOS needs Ira restarted before the screen can be read.
    public var onRestartNeeded: @Sendable () -> Void = {}

    /// How long a tool may take on this Mac: always under the server's 25 seconds,
    /// so a stuck tool answers with a reason instead of leaving Ira waiting.
    public static func deadline(for name: String) -> Double {
        switch name {
        case "screen_read": return 15
        case "files_find": return 12
        case "mail_search", "mail_read", "mail_draft", "notes_search", "notes_read", "notes_add", "messages_send",
            "shortcuts_run", "code_task_start", "code_task_push", "browser_tabs", "browser_show_tab":
            return 22
        default: return 10
        }
    }

    /// What to say when a tool ran out of time.
    static func lateMessage(_ name: String, screenPermitted: Bool) -> String {
        if name == "screen_read" && screenPermitted {
            return ScreenText.restartNeeded
        }
        return "that took too long on this Mac. If macOS is showing a permission prompt, answer it, then ask again"
    }

    public func call(_ name: String, args: JSONValue) async throws -> JSONValue {
        guard args.objectValue != nil else { throw ToolFailure("arguments must be an object") }
        let started = Date()
        var target = Toolbox.target(name, args)
        do {
            let (content, readTarget) = try await withTimeout(Toolbox.deadline(for: name)) {
                try await self.run(name, args)
            }
            if let readTarget { target = readTarget }
            record(Activity(at: started, tool: name, target: target, ok: true))
            return content
        } catch is TimedOut {
            record(Activity(at: started, tool: name, target: target, ok: false))
            let permitted = name == "screen_read" && ScreenText.permitted
            if permitted { onRestartNeeded() }
            throw ToolFailure(Toolbox.lateMessage(name, screenPermitted: permitted))
        } catch let failure as ToolFailure {
            record(Activity(at: started, tool: name, target: target, ok: false))
            if failure.message == ScreenText.restartNeeded { onRestartNeeded() }
            throw failure
        } catch {
            record(Activity(at: started, tool: name, target: target, ok: false))
            throw error
        }
    }

    /// Run one tool; the second value is a better "What I read" target, when known after.
    private func run(_ name: String, _ args: JSONValue) async throws -> (JSONValue, String?) {
        let content: JSONValue
        do {
            switch name {
            case "files_find": content = try await findFiles(args.objectValue!)
            case "file_read": content = try await readFile(args.objectValue!)
            case "file_open": content = try await openFile(args.objectValue!)
            case "screen_read":
                let read = try await readScreen(args.objectValue!)
                return (read.content, read.target)
            case "browser_tabs": content = try await BrowserTools.listTabs(args)
            case "browser_show_tab": content = try await BrowserTools.showTab(args)
            case "contacts_lookup":
                let query = try ToolArgs(args, allowed: ["query"]).required("query", limit: 200, what: "who: a name, number or email")
                content = try await ContactsTool.lookup(query)
            case "calendar_read": content = try await eventKit.calendarRead(args)
            case "calendar_add": content = try await eventKit.calendarAdd(args)
            case "reminders_list": content = try await eventKit.remindersList(args)
            case "reminders_add": content = try await eventKit.remindersAdd(args)
            case "reminders_done": content = try await eventKit.remindersDone(args)
            case "mail_search": content = try await AppleScriptTools.mailSearch(args)
            case "mail_read": content = try await AppleScriptTools.mailRead(args)
            case "mail_draft": content = try await AppleScriptTools.mailDraft(args)
            case "messages_send": content = try await AppleScriptTools.messagesSend(args)
            case "notes_search": content = try await AppleScriptTools.notesSearch(args)
            case "notes_read": content = try await AppleScriptTools.notesRead(args)
            case "notes_add": content = try await AppleScriptTools.notesAdd(args)
            case "app_open": content = try await AppTools.appOpen(args, home: policy().home)
            case "url_open": content = try await AppTools.urlOpen(args)
            case "vscode_open": content = try await AppTools.vscodeOpen(args, policy: policy(), promptTemplate: TaskSettings.load()?.promptURI)
            case "clipboard_read": content = try await AppTools.clipboardRead(args)
            case "shortcuts_list": content = try await AppTools.shortcutsList(args)
            case "shortcuts_run": content = try await AppTools.shortcutsRun(args)
            case "code_task_start": content = try await tasks.start(args)
            case "code_task_status": content = try await tasks.status(args)
            case "code_task_list": content = try await tasks.list(args)
            case "code_task_stop": content = try await tasks.stop(args)
            case "code_task_push": content = try await tasks.push(args)
            default:
                throw ToolFailure("this Mac has no tool '\(name)'")
            }
        }
        return (content, nil)
    }

    /// What "What I read" shows for a call: a path, a name or a search, never contents.
    static func target(_ name: String, _ args: JSONValue) -> String {
        func text(_ key: String) -> String? {
            args[key]?.stringValue.map { String($0.prefix(120)) }
        }
        switch name {
        case "files_find": return describeSearch(args.objectValue ?? [:])
        case "file_read", "file_open", "vscode_open": return shown(args["path"]?.stringValue.map { String($0.prefix(1000)) })
        case "browser_tabs": return text("browser") ?? "all browsers"
        case "browser_show_tab": return text("match") ?? text("id") ?? ""
        case "contacts_lookup": return text("query") ?? ""
        case "calendar_read": return text("from") ?? "today"
        case "calendar_add", "reminders_add", "notes_add": return text("title") ?? ""
        case "reminders_done": return text("title") ?? text("id") ?? ""
        case "mail_search", "notes_search": return text("query").map { "“\($0)”" } ?? "latest"
        case "mail_read", "notes_read": return "one \(name.hasPrefix("mail") ? "email" : "note")"
        case "mail_draft":
            let to = (args["to"]?.arrayValue?.compactMap(\.stringValue) ?? [text("to")].compactMap { $0 }).joined(separator: ", ")
            return "to \(to)"
        case "messages_send": return "to \(text("name") ?? text("to") ?? "")"
        case "app_open", "shortcuts_run": return text("name") ?? ""
        case "url_open": return text("url").flatMap { AppTools.webURL($0)?.host } ?? ""
        case "code_task_start": return text("repo") ?? ""
        case "code_task_status", "code_task_stop", "code_task_push": return text("id") ?? ""
        default: return ""
        }
    }

    static func shown(_ path: String?) -> String {
        guard let path, !path.isEmpty else { return "" }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
    }

    static func describeSearch(_ args: [String: JSONValue]) -> String {
        var parts: [String] = []
        if let query = args["query"]?.stringValue, !query.isEmpty { parts.append("“\(query.prefix(60))”") }
        if let kind = args["kind"]?.stringValue { parts.append(kind) }
        if let days = args["modifiedWithinDays"]?.intValue { parts.append("last \(days) days") }
        if let folder = args["folder"]?.stringValue { parts.append("in \(folder.prefix(80))") }
        return parts.isEmpty ? "recent files" : parts.joined(separator: ", ")
    }

    static func check(_ args: [String: JSONValue], allowed: Set<String>) throws {
        let unknown = Set(args.keys).subtracting(allowed).sorted()
        if !unknown.isEmpty {
            throw ToolFailure("unknown argument(s): \(unknown.joined(separator: ", "))")
        }
    }

    static func text(_ args: [String: JSONValue], _ name: String, limit: Int = 500) throws -> String? {
        guard let value = args[name], !value.isNull else { return nil }
        guard let text = value.stringValue else { throw ToolFailure("\(name) must be text") }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : String(trimmed.prefix(limit))
    }

    static func number(_ args: [String: JSONValue], _ name: String, _ range: ClosedRange<Int>) throws -> Int? {
        guard let value = args[name], !value.isNull else { return nil }
        guard let number = value.doubleValue, number.isFinite else { throw ToolFailure("\(name) must be a number") }
        return min(max(Int(number), range.lowerBound), range.upperBound)
    }

    // files_find

    func findFiles(_ args: [String: JSONValue]) async throws -> JSONValue {
        try Toolbox.check(args, allowed: ["query", "kind", "modifiedWithinDays", "folder"])
        let policy = self.policy()
        let kind = try Toolbox.text(args, "kind")?.lowercased()
        if let kind, FileSearch.kinds[kind] == nil {
            throw ToolFailure("kind must be one of: \(FileSearch.kinds.keys.sorted().joined(separator: ", "))")
        }
        let query = FileSearch.Query(
            text: try Toolbox.text(args, "query", limit: 200), kind: kind,
            modifiedWithinDays: try Toolbox.number(args, "modifiedWithinDays", 1...3650),
            folder: try Toolbox.text(args, "folder"))
        var scopes = policy.roots
        if let folder = query.folder {
            let path = FileSearch.folderPath(folder, home: policy.home)
            if let refusal = policy.refusal(path) { throw ToolFailure(refusal) }
            scopes = [URL(fileURLWithPath: PathPolicy.expand(path, home: policy.home)?.path ?? path)]
        }
        let predicate = FileSearch.predicate(for: query)
        let found = await FileSearch.run(predicate, scopes: scopes, policy: policy)
        let formatter = ISO8601DateFormatter()
        let results: [JSONValue] = found.map { file in
            var entry: [String: JSONValue] = [
                "name": .string(file.url.lastPathComponent),
                "folder": .string(policy.display(file.url.deletingLastPathComponent())),
                "path": .string(file.url.path),
            ]
            if let kind = file.kind { entry["kind"] = .string(kind) }
            if let size = file.size {
                entry["size"] = .number(Double(size))
                entry["sizeText"] = .string(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
            }
            if let modified = file.modified { entry["modified"] = .string(formatter.string(from: modified)) }
            return .object(entry)
        }
        log.info("files_find found \(found.count)")
        return [
            "results": .array(results),
            "count": .number(Double(found.count)),
            "summary": .string(Toolbox.findSummary(found, policy: policy)),
        ]
    }

    static func findSummary(_ found: [FileSearch.Found], policy: PathPolicy) -> String {
        if found.isEmpty { return "No files matched." }
        let names = found.prefix(5).map { "\($0.url.lastPathComponent) in \(policy.display($0.url.deletingLastPathComponent()))" }
        let more = found.count > 5 ? " and \(found.count - 5) more" : ""
        return "Found \(found.count) file\(found.count == 1 ? "" : "s"): \(names.joined(separator: "; "))\(more)."
    }

    // file_read

    func readFile(_ args: [String: JSONValue]) async throws -> JSONValue {
        try Toolbox.check(args, allowed: ["path", "maxChars"])
        guard let path = try Toolbox.text(args, "path", limit: 2000) else { throw ToolFailure("say which file: its path") }
        let policy = self.policy()
        if let refusal = policy.refusal(path) { throw ToolFailure(refusal) }
        let maxChars = try Toolbox.number(args, "maxChars", 200...Toolbox.maxText) ?? Toolbox.maxText
        guard let url = PathPolicy.expand(path, home: policy.home) else { throw ToolFailure("give the full path") }
        let read = try await Task.detached(priority: .userInitiated) {
            try FileText.read(url, maxChars: maxChars)
        }.value
        log.info("file_read \(read.kind) \(read.text.count) chars")
        var content: [String: JSONValue] = [
            "name": .string(url.lastPathComponent),
            "path": .string(url.path),
            "kind": .string(read.kind),
            "chars": .number(Double(read.text.count)),
            "truncated": .bool(read.truncated),
            "text": .string(read.text),
        ]
        if let pages = read.pages { content["pages"] = .number(Double(pages)) }
        let cut = read.truncated ? ", the first \(read.text.count) characters" : ""
        content["summary"] = .string("Read \(url.lastPathComponent) (\(read.kind)\(cut)).")
        return .object(content)
    }

    // file_open

    /// What `file_open` never opens: things that run code when opened.
    public static let neverOpen: Set<String> = [
        "command", "tool", "sh", "zsh", "bash", "csh", "fish", "terminal", "workflow", "action",
        "scpt", "scptd", "applescript", "osascript", "pkg", "mpkg", "jar", "prefpane", "kext",
        "plugin", "bundle", "webloc", "inetloc", "fileloc", "url", "mobileconfig", "dmg", "py",
        "rb", "pl", "js",
    ]

    static let appFolders = ["/Applications", "/System/Applications", "/System/Cryptexes/App/System/Applications"]

    /// Why a path may not be opened, or nil.
    public static func openRefusal(_ path: String, policy: PathPolicy) -> String? {
        guard let url = PathPolicy.expand(path, home: policy.home) else { return "give the full path" }
        let real = PathPolicy.resolve(url)
        let ext = real.pathExtension.lowercased()
        if ext == "app" || url.pathExtension.lowercased() == "app" {
            // Safari and other system apps are links into a sealed volume: accept either path.
            let folders = appFolders.map { URL(fileURLWithPath: $0) } + [policy.home.appendingPathComponent("Applications")]
            let inside = folders.contains { PathPolicy.isInside(real, $0) || PathPolicy.isInside(url.standardizedFileURL, $0) }
            return inside ? nil : "I open apps only from the Applications folders"
        }
        if let refusal = policy.refusal(path) { return refusal }
        if neverOpen.contains(ext) { return "I never open scripts, installers or links: they could run something" }
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: real.path, isDirectory: &isDirectory), !isDirectory.boolValue,
            FileManager.default.isExecutableFile(atPath: real.path)
        {
            return "I never open programs or scripts"
        }
        return nil
    }

    func openFile(_ args: [String: JSONValue]) async throws -> JSONValue {
        try Toolbox.check(args, allowed: ["path"])
        guard let path = try Toolbox.text(args, "path", limit: 2000) else { throw ToolFailure("say which file: its path") }
        let policy = self.policy()
        if let refusal = Toolbox.openRefusal(path, policy: policy) { throw ToolFailure(refusal) }
        guard let url = PathPolicy.expand(path, home: policy.home),
            FileManager.default.fileExists(atPath: url.path)
        else { throw ToolFailure("there is nothing at that path") }
        guard await opener(url) else { throw ToolFailure("macOS could not open it") }
        log.info("file_open done")
        return ["opened": .string(url.path), "summary": .string("Opened \(url.lastPathComponent).")]
    }

    // screen_read

    func readScreen(_ args: [String: JSONValue]) async throws -> (content: JSONValue, target: String) {
        try Toolbox.check(args, allowed: [])
        guard ScreenText.permitted else { throw ToolFailure(ScreenText.notPermitted) }
        // Allowed after Ira started: macOS applies it only to a fresh start, and a
        // capture now would hang. Say so at once instead.
        if !ScreenText.permittedAtLaunch { throw ToolFailure(ScreenText.restartNeeded) }
        guard let front = await frontApp() else { throw ToolFailure("no app is in front") }
        let bundleID = await MainActor.run { NSRunningApplication(processIdentifier: front.pid)?.bundleIdentifier }
        if let refusal = ScreenText.refusal(bundleID: bundleID, name: front.name) { throw ToolFailure(refusal) }
        guard let window = ScreenText.frontWindow(of: front.pid) else {
            throw ToolFailure("\(front.name) has no window open in front")
        }
        let app = window.app.isEmpty ? front.name : window.app
        let target = window.title.isEmpty ? app : "\(app) — \(window.title)"
        let image: CGImage
        do {
            image = try await withTimeout(10) { try await ScreenText.capture(window) }
        } catch is TimedOut {
            throw ToolFailure(
                "I can't read \(app)'s window: macOS did not hand it over in time. If macOS is asking whether Ira may record the screen, answer it, then ask again")
        }
        let text = try await Task.detached(priority: .userInitiated) { try ScreenText.recognize(image) }.value
        let read = FileText.cut(text, kind: "screen", maxChars: Toolbox.maxText)
        log.info("screen_read \(read.text.count) chars")
        let lines = read.text.isEmpty ? 0 : read.text.split(separator: "\n").count
        let content: JSONValue = [
            "app": .string(app),
            "window": .string(window.title),
            "text": .string(read.text),
            "chars": .number(Double(read.text.count)),
            "truncated": .bool(read.truncated),
            "summary": .string(
                read.text.isEmpty
                    ? "The \(target) window shows no text I can read."
                    : "Read the \(target) window: \(lines) line\(lines == 1 ? "" : "s") of text."),
        ]
        return (content, target)
    }
}
