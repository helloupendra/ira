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
        case "reminders_set": return "Set a reminder"
        case "mail_search": return "Searched your mail"
        case "mail_draft": return "Drafted an email"
        case "messages_send": return "Sent a message"
        case "notes_search": return "Searched your notes"
        case "notes_add": return "Added a note"
        case "app_open": return "Opened an app"
        case "url_open": return "Opened a web page"
        case "clipboard_read": return "Read the clipboard"
        case "shortcuts_list": return "Listed your shortcuts"
        case "shortcuts_run": return "Ran a shortcut"
        case "mac_type": return "Typed on your Mac"
        case "mac_keys": return "Pressed keys"
        case "mac_click": return "Clicked"
        case "mac_scroll": return "Scrolled"
        case "mac_menu": return "Chose a menu item"
        case "code_task_start": return "Started a coding task"
        case "code_task_status": return "Checked a coding task"
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
    private var control: ControlTools { ControlTools(frontApp: frontApp, log: log) }
    /// Which of Documents, Desktop and Downloads Ira may look into.
    public let folderGrants: FolderGrants
    /// Coding tasks; their done and failed events go out through `announce`.
    public let tasks: CodeTasks

    public init(
        policy: @escaping @Sendable () -> PathPolicy,
        frontApp: @escaping FrontApp,
        opener: @escaping Opener = Toolbox.workspaceOpen,
        tasks: CodeTasks = CodeTasks(),
        folderGrants: FolderGrants = FolderGrants(),
        log: IraLog = .shared,
        record: @escaping @Sendable (Activity) -> Void
    ) {
        self.policy = policy
        self.frontApp = frontApp
        self.opener = opener
        self.tasks = tasks
        self.folderGrants = folderGrants
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
        case "mac_type", "mac_keys", "mac_click", "mac_scroll", "mac_menu": return 20
        case "mail_search", "mail_draft", "notes_search", "notes_add", "messages_send",
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
            case "file_open":
                // In VS Code, a folder too (a repository), with a request filled in for its assistant.
                if args["app"]?.stringValue == "vscode" {
                    var rest = args.objectValue!
                    rest["app"] = nil
                    content = try await AppTools.vscodeOpen(.object(rest), policy: policy(), promptTemplate: TaskSettings.load()?.promptURI)
                } else {
                    content = try await openFile(args.objectValue!)
                }
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
            case "reminders_set":
                if args["done"]?.boolValue == true {
                    content = try await eventKit.remindersDone(Toolbox.only(args, ["id", "title"], what: "marking a reminder done", drop: ["done"]))
                } else {
                    content = try await eventKit.remindersAdd(Toolbox.only(args, ["title", "due", "list", "notes"], what: "adding a reminder", drop: ["done"]))
                }
            case "mail_search":
                content = args["id"] == nil
                    ? try await AppleScriptTools.mailSearch(args)
                    : try await AppleScriptTools.mailRead(Toolbox.only(args, ["id", "maxChars"], what: "reading one email"))
            case "mail_draft": content = try await AppleScriptTools.mailDraft(args)
            case "messages_send": content = try await AppleScriptTools.messagesSend(args)
            case "notes_search":
                content = args["id"] == nil
                    ? try await AppleScriptTools.notesSearch(args)
                    : try await AppleScriptTools.notesRead(Toolbox.only(args, ["id", "maxChars"], what: "reading one note"))
            case "notes_add": content = try await AppleScriptTools.notesAdd(args)
            case "app_open": content = try await AppTools.appOpen(args, home: policy().home)
            case "url_open": content = try await AppTools.urlOpen(args)
            case "clipboard_read": content = try await AppTools.clipboardRead(args)
            case "shortcuts_list": content = try await AppTools.shortcutsList(args)
            case "shortcuts_run": content = try await AppTools.shortcutsRun(args)
            case "mac_type": content = try await control.type(args)
            case "mac_keys": content = try await control.keys(args)
            case "mac_click": content = try await control.click(args)
            case "mac_scroll": content = try await control.scroll(args)
            case "mac_menu": content = try await control.menu(args)
            case "code_task_start": content = try await tasks.start(args)
            case "code_task_status":
                content = args["id"] == nil ? try await tasks.list(args) : try await tasks.status(args)
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
        case "file_read", "file_open": return shown(args["path"]?.stringValue.map { String($0.prefix(1000)) })
        case "browser_tabs": return text("browser") ?? "all browsers"
        case "browser_show_tab": return text("match") ?? text("id") ?? ""
        case "contacts_lookup": return text("query") ?? ""
        case "calendar_read": return text("from") ?? "today"
        case "calendar_add", "notes_add": return text("title") ?? ""
        case "reminders_set": return text("title") ?? text("id") ?? ""
        case "mail_search", "notes_search":
            if args["id"] != nil { return "one \(name.hasPrefix("mail") ? "email" : "note")" }
            return text("query").map { "“\($0)”" } ?? "latest"
        case "mail_draft":
            let to = (args["to"]?.arrayValue?.compactMap(\.stringValue) ?? [text("to")].compactMap { $0 }).joined(separator: ", ")
            return "to \(to)"
        case "messages_send": return "to \(text("name") ?? text("to") ?? "")"
        case "app_open", "shortcuts_run": return text("name") ?? ""
        case "url_open": return text("url").flatMap { AppTools.webURL($0)?.host } ?? ""
        case "mac_type": return "\(args["text"]?.stringValue?.count ?? 0) characters" + (text("app").map { " in \($0)" } ?? "")
        case "mac_keys": return (text("keys") ?? "") + (text("app").map { " in \($0)" } ?? "")
        case "mac_click": return (text("label").map { "“\($0)”" } ?? "") + (text("app").map { " in \($0)" } ?? "")
        case "mac_scroll": return (text("direction") ?? "") + (text("app").map { " in \($0)" } ?? "")
        case "mac_menu": return (text("path") ?? "") + (text("app").map { " in \($0)" } ?? "")
        case "code_task_start": return text("repo") ?? ""
        case "code_task_status": return text("id") ?? "all tasks"
        case "code_task_stop", "code_task_push": return text("id") ?? ""
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

    /// The arguments for one use of a tool that does two things, refusing the other's.
    static func only(_ args: JSONValue, _ keys: Set<String>, what: String, drop: Set<String> = []) throws -> JSONValue {
        var object = args.objectValue ?? [:]
        for key in drop { object[key] = nil }
        let extra = Set(object.keys).subtracting(keys).sorted()
        if !extra.isEmpty { throw ToolFailure("\(extra.joined(separator: ", ")) do not go with \(what)") }
        return .object(object)
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
        // Look at the guarded folders this search covers: macOS answers at once for
        // those it was asked about (a "no" since switched on counts now), and asks
        // the person, once, about the others. Spotlight would skip them in silence.
        let grants = folderGrants
        let covered = grants.covered(by: scopes)
        let unasked = covered.filter { grants.access($0) == .notAsked }
        if !unasked.isEmpty { NotificationCenter.default.post(name: PermissionPrompt.asking, object: nil) }
        _ = try? await withTimeout(8) {
            for folder in covered {
                if grants.access(folder) == .notAsked { grants.ask(folder) } else { grants.recheck(folder) }
            }
        }
        if !unasked.isEmpty { NotificationCenter.default.post(name: PermissionPrompt.asked, object: nil) }
        let blocked = grants.blocked(in: scopes)
        var found: [FileSearch.Found]
        if kind == "folder", let words = query.words.isEmpty ? nil : query.words {
            found = await findFolders(words.joined(separator: " "), scopes: scopes, policy: policy, blocked: blocked)
        } else {
            found = await FileSearch.run(FileSearch.predicate(for: query), scopes: scopes, policy: policy)
        }
        found = Array(found.prefix(FileSearch.maxResults))
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
        var content: [String: JSONValue] = [
            "results": .array(results),
            "count": .number(Double(found.count)),
            "summary": .string(Toolbox.findSummary(found, policy: policy, notSearched: blocked, grants: grants)),
        ]
        if !blocked.isEmpty { content["notSearched"] = .array(blocked.map { .string($0) }) }
        return .object(content)
    }

    /// Folders by what the person calls them: Spotlight's candidates ranked by
    /// `FolderMatch`, and when Spotlight has none, a short walk of the usual
    /// places (3 levels, 2 seconds), never into a folder Ira may not open.
    func findFolders(_ words: String, scopes: [URL], policy: PathPolicy, blocked: [String]) async -> [FileSearch.Found] {
        let candidates = await FileSearch.run(
            FileSearch.folderPredicate(for: FolderMatch.words(words)), scopes: scopes, policy: policy, limit: 300)
        var ranked: [(FileSearch.Found, Double)] = candidates.compactMap { found in
            FolderMatch.score(query: words, name: found.url.lastPathComponent).map { (found, $0) }
        }
        if ranked.isEmpty {
            let home = policy.home
            let places = ["Documents/GitHub", "Documents", "Desktop", "Downloads", "Developer"]
                .filter { place in !blocked.contains { place == $0 || place.hasPrefix($0 + "/") } }
                .map { home.appendingPathComponent($0) }
                .filter { url in scopes.contains { PathPolicy.isInside(url, $0) || PathPolicy.isInside($0, url) } }
            let walked = await Task.detached(priority: .userInitiated) {
                FolderMatch.walk(places, query: words, policy: policy)
            }.value
            ranked = walked.map { item in
                let modified = try? item.url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
                return (FileSearch.Found(url: item.url, kind: "Folder", size: nil, modified: modified), item.score)
            }
        }
        var seen = Set<String>()
        return ranked.sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.0.url.path.count < $1.0.url.path.count }
            .map(\.0).filter { seen.insert($0.url.path).inserted }
    }

    static func findSummary(
        _ found: [FileSearch.Found], policy: PathPolicy, notSearched: [String] = [], grants: FolderGrants? = nil
    ) -> String {
        let note = grants.map { $0.notSearched(notSearched) } ?? FolderGrants.notSearched(notSearched)
        let unsearched = note.map { " " + $0 } ?? ""
        if found.isEmpty { return "Nothing matched where I could look." + unsearched }
        let names = found.prefix(5).map { "\($0.url.lastPathComponent) in \(policy.display($0.url.deletingLastPathComponent()))" }
        let more = found.count > 5 ? " and \(found.count - 5) more" : ""
        return "Found \(found.count) file\(found.count == 1 ? "" : "s"): \(names.joined(separator: "; "))\(more)." + unsearched
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
            if NeverApps.contains(bundleID: Bundle(url: real)?.bundleIdentifier, name: real.deletingPathExtension().lastPathComponent) {
                return NeverApps.refusal
            }
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
        try Toolbox.check(args, allowed: ["path", "app"])
        if let app = try Toolbox.text(args, "app"), app != "default" { throw ToolFailure("app must be default or vscode") }
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
        guard ScreenText.permitted else { throw ToolFailure(ScreenText.notPermittedNow) }
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
            // The bundle id: an approval for trusted apps checks it; the name is for people.
            "app": .string(bundleID ?? ""),
            "appName": .string(app),
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
