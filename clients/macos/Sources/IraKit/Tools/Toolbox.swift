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
        default: return tool
        }
    }
}

/// The tools this Mac offers Ira, with their skills and tiers.
///
/// * `files` skill: `files_find` (Tier 0), `file_read` (Tier 0), `file_open` (Tier 1:
///   small and undoable, Ira does it and says so);
/// * `screen` skill: `screen_read` (Tier 0, only when asked; the skill itself is
///   switched on with the PIN).
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

    public init(
        policy: @escaping @Sendable () -> PathPolicy,
        frontApp: @escaping FrontApp,
        opener: @escaping Opener = Toolbox.workspaceOpen,
        log: IraLog = .shared,
        record: @escaping @Sendable (Activity) -> Void
    ) {
        self.policy = policy
        self.frontApp = frontApp
        self.opener = opener
        self.log = log
        self.record = record
    }

    public static let workspaceOpen: Opener = { url in
        await MainActor.run { NSWorkspace.shared.open(url) }
    }

    // MARK: The hello

    public var definitions: [JSONValue] { Toolbox.definitions }

    public static let definitions: [JSONValue] = [
        [
            "name": "files_find",
            "description": .string(
                "Find files on this Mac with Spotlight, by words in the name or inside the file, by kind and by date. Returns up to 20: name, folder, path, kind, size and when it was last changed, newest first. Use it for 'where is that file', 'the PDF I downloaded yesterday'."),
            "parameters": [
                "type": "object",
                "properties": [
                    "query": ["type": "string", "description": "Words from the file's name or its text. Leave empty to list recent files of a kind."],
                    "kind": [
                        "type": "string",
                        "enum": .array(FileSearch.kinds.keys.sorted().map { .string($0) }),
                        "description": "The kind of file.",
                    ],
                    "modifiedWithinDays": [
                        "type": "integer", "minimum": 1, "maximum": 3650,
                        "description": "Only files changed or added in the last this many days (1 means the last 24 hours).",
                    ],
                    "folder": ["type": "string", "description": "Look only in this folder: Downloads, Desktop, Documents, or a path such as ~/Projects."],
                ],
                "additionalProperties": false,
            ],
            "skill": "files",
            "tier": 0,
        ],
        [
            "name": "file_read",
            "description": .string(
                "Read the text of one file on this Mac: PDF, Word (.docx), RTF, plain text or Markdown, up to 20,000 characters. Give the full path from files_find. Never keychains, ~/Library or hidden files."),
            "parameters": [
                "type": "object",
                "properties": [
                    "path": ["type": "string", "description": "The file's full path, e.g. ~/Downloads/invoice.pdf."],
                    "maxChars": ["type": "integer", "minimum": 200, "maximum": .number(Double(maxText)), "description": "Read at most this many characters (default and most: 20,000)."],
                ],
                "required": ["path"],
                "additionalProperties": false,
            ],
            "skill": "files",
            "tier": 0,
        ],
        [
            "name": "file_open",
            "description": .string(
                "Open a file on this Mac in its usual app, or open an app. Say that you opened it. Never runs scripts or installers."),
            "parameters": [
                "type": "object",
                "properties": [
                    "path": ["type": "string", "description": "The file's or the app's full path."],
                ],
                "required": ["path"],
                "additionalProperties": false,
            ],
            "skill": "files",
            "tier": 1,
        ],
        [
            "name": "screen_read",
            "description": .string(
                "Read the text of the window in front on this Mac, in any app, only when the person asks what is on their screen. Returns the app's name, the window's title and the text, read on the Mac; no picture is sent."),
            "parameters": ["type": "object", "properties": [:], "additionalProperties": false],
            "skill": "screen",
            "tier": 0,
        ],
    ]

    // MARK: Calls

    public func call(_ name: String, args: JSONValue) async throws -> JSONValue {
        guard let args = args.objectValue else { throw ToolFailure("arguments must be an object") }
        let started = Date()
        var target = ""
        do {
            let content: JSONValue
            switch name {
            case "files_find":
                target = Toolbox.describeSearch(args)
                content = try await findFiles(args)
            case "file_read":
                target = Toolbox.shown(args["path"]?.stringValue)
                content = try await readFile(args)
            case "file_open":
                target = Toolbox.shown(args["path"]?.stringValue)
                content = try await openFile(args)
            case "screen_read":
                let read = try await readScreen(args)
                target = read.target
                content = read.content
            default:
                throw ToolFailure("this Mac has no tool '\(name)'")
            }
            record(Activity(at: started, tool: name, target: target, ok: true))
            return content
        } catch {
            record(Activity(at: started, tool: name, target: target, ok: false))
            throw error
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
        guard let front = await frontApp() else { throw ToolFailure("no app is in front") }
        guard let window = ScreenText.frontWindow(of: front.pid) else {
            throw ToolFailure("\(front.name) has no window open in front")
        }
        let app = window.app.isEmpty ? front.name : window.app
        let target = window.title.isEmpty ? app : "\(app) — \(window.title)"
        let image = try await ScreenText.capture(window)
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
