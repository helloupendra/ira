import Foundation

/// The AI coding sessions on this Mac, so the person can ask "what is the AI doing?" from
/// anywhere: a coding agent's sessions, from the transcripts it keeps per project
/// (`<folder>/<project>/<session id>.jsonl`, the folders listed as `transcripts` in
/// tasks.json), whether it runs in VS Code, a terminal or as Ira's coding task; and Ira's
/// coding tasks.
///
/// Everything is read and summarised here. Only a short summary leaves the Mac: the project's
/// folder name, the state, the task list's count and its current item, the last step as a
/// phrase, and the person's latest request and the AI's last answer, cut to about 200
/// characters. Every excerpt goes through `SecretFilter`. Never a transcript, a file's
/// contents, a command or a tool's output.
///
/// Sessions Ira did not start are read only: to stop one, the person stops it where it runs.
public struct AISession: Equatable, Sendable {
    public enum State: String, Sendable {
        /// Working on a step, or thinking.
        case working
        /// Its turn ended, or it asked something: the person's move.
        case waiting
        /// Quiet for long, or a run that ended.
        case finished
    }

    public struct Step: Equatable, Sendable {
        public var at: Date?
        public var text: String
    }

    public var id: String
    public var project: String
    public var title: String?
    /// Where it runs: "VS Code", "a terminal", "headless", or "Ira's task t1a2b3".
    public var place: String
    public var state: State
    /// Why it looks so: "asked you a question", "quiet for 6 min: …".
    public var note: String?
    public var done: Int?
    public var total: Int?
    /// The task list's item in progress.
    public var current: String?
    /// The last step, as a phrase.
    public var doing: String?
    public var request: String?
    public var answer: String?
    public var updated: Date
    /// The last 10 steps, oldest first.
    public var steps: [Step]
    /// Ira's own task (it can stop it); nil for sessions Ira only reads.
    public var task: String?
    /// The person can talk to it from their phone (an Ira chat task that is on: code_task_say).
    public var talk = false
}

/// One coding agent's transcript, summarised from its last lines.
public enum TranscriptSummary {
    public static let excerpt = 200
    public static let maxSteps = 10
    /// A step with nothing written for this long may be a long command, or a permission prompt.
    public static let quietAfter: Double = 120
    /// Thinking with nothing written for this long: probably stopped.
    public static let thinkingFor: Double = 300
    /// A turn that ended this long ago, or a session quiet this long, is finished.
    public static let idleAfter: Double = 1800
    public static let lostAfter: Double = 3600

    /// A short, secret-masked excerpt.
    public static func clip(_ text: String, _ limit: Int = excerpt) -> String {
        AgentOutput.short(SecretFilter.mask(text), limit)
    }

    static let injected = [
        "system-reminder", "ide_selection", "ide_opened_file", "command-name", "command-message", "command-args",
        "local-command-stdout", "local-command-stderr", "local-command-caveat", "user-prompt-submit-hook",
        "task-notification", "cross-session-message", "pasted_content",
    ]

    /// The person's own words in a prompt: without what the editor or the agent added.
    static func ownWords(_ text: String) -> String {
        var out = text
        for tag in injected {
            out = out.replacingOccurrences(of: "<\(tag)\\b[^>]*>[\\s\\S]*?</\(tag)>", with: " ", options: .regularExpression)
        }
        return out.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    static func date(_ value: String?) -> Date? {
        guard let value else { return nil }
        let precise = ISO8601DateFormatter()
        precise.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return precise.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }

    /// Where a session runs, from its entrypoint.
    static func place(_ entrypoint: String?) -> String {
        guard let entrypoint, !entrypoint.isEmpty else { return "a coding agent" }
        if entrypoint.contains("vscode") { return "VS Code" }
        if entrypoint == "cli" { return "a terminal" }
        if entrypoint.hasPrefix("sdk") { return "headless" }
        return clip(entrypoint, 40)
    }

    /// The last step, as a phrase: what kind of thing, and a file's name; never a command,
    /// a file's contents or a tool's output.
    public static func phrase(_ tool: String, _ input: JSONValue) -> String {
        func file(_ key: String = "file_path") -> String {
            input[key]?.stringValue.map { ($0 as NSString).lastPathComponent }.map { " \(clip($0, 60))" } ?? ""
        }
        func said(_ key: String) -> String? {
            input[key]?.stringValue.map { clip($0, 90) }.flatMap { $0.isEmpty ? nil : $0 }
        }
        switch tool {
        case "Bash": return said("description") ?? "ran a command"
        case "BashOutput", "TaskOutput": return "checked a running command"
        case "KillShell", "KillBash", "TaskStop": return "stopped a running command"
        case "Read": return "read" + file()
        case "Edit", "MultiEdit": return "edited" + file()
        case "Write": return "wrote" + file()
        case "NotebookEdit": return "edited" + file("notebook_path")
        case "Grep", "Glob", "LS": return "searched the code"
        case "WebSearch": return "searched the web"
        case "WebFetch": return "read a web page" + (input["url"]?.stringValue.flatMap { URL(string: $0)?.host }.map { " (\($0))" } ?? "")
        case "Agent", "Task": return "started a helper" + (said("description").map { ": \($0)" } ?? "")
        case "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet": return "updated its task list"
        case "AskUserQuestion": return "asked you a question"
        case "ExitPlanMode": return "showed you a plan"
        case "SendMessage": return "messaged another session"
        case "Skill": return "used a skill" + (said("skill").map { " (\($0))" } ?? "")
        case "ToolSearch": return "looked up a tool"
        case "ScheduleWakeup", "CronCreate": return "scheduled a check"
        case "Monitor": return "watched a running job"
        default:
            if tool.hasPrefix("mcp__") {
                let parts = tool.split(separator: "_", omittingEmptySubsequences: true)
                return "used \(parts.dropFirst().first.map(String.init) ?? "a connector")"
            }
            return "used \(clip(tool, 40))"
        }
    }

    struct Item: Equatable {
        var text: String
        var active: String?
        var status: String
    }

    /// The session's latest task list: TodoWrite's whole list, or the task tools' changes.
    struct TaskList {
        var todos: [Item]?
        var todosAt = -1
        var tasks: [(id: String, item: Item)] = []
        var tasksAt = -1
        var pendingCreates: [String: String] = [:]  // tool_use id -> the id given
        var nextID = 1

        mutating func todoWrite(_ input: JSONValue, at index: Int) {
            guard let list = input["todos"]?.arrayValue else { return }
            todos = list.compactMap { entry in
                guard let text = entry["content"]?.stringValue ?? entry["subject"]?.stringValue else { return nil }
                return Item(text: text, active: entry["activeForm"]?.stringValue, status: entry["status"]?.stringValue ?? "pending")
            }
            todosAt = index
        }

        mutating func create(_ input: JSONValue, useID: String?, at index: Int) {
            guard let text = input["subject"]?.stringValue ?? input["content"]?.stringValue else { return }
            let id = String(nextID)
            nextID += 1
            tasks.append((id, Item(text: text, active: input["activeForm"]?.stringValue, status: "pending")))
            if let useID { pendingCreates[useID] = id }
            tasksAt = index
        }

        /// The task tool's answer names the id it gave ("Task #3 created"): use that one.
        mutating func created(useID: String, result: String) {
            guard let given = pendingCreates.removeValue(forKey: useID),
                let match = result.range(of: #"#(\d+)"#, options: .regularExpression)
            else { return }
            let real = String(result[match].dropFirst())
            if real != given, let index = tasks.firstIndex(where: { $0.id == given }) {
                tasks[index].id = real
                nextID = max(nextID, (Int(real) ?? 0) + 1)
            }
        }

        mutating func update(_ input: JSONValue, at index: Int) {
            guard let id = input["taskId"]?.stringValue ?? input["taskId"]?.intValue.map(String.init) ?? input["id"]?.stringValue,
                let position = tasks.firstIndex(where: { $0.id == id })
            else { return }
            if input["status"]?.stringValue == "deleted" {
                tasks.remove(at: position)
            } else {
                if let status = input["status"]?.stringValue { tasks[position].item.status = status }
                if let subject = input["subject"]?.stringValue { tasks[position].item.text = subject }
                if let active = input["activeForm"]?.stringValue { tasks[position].item.active = active }
            }
            tasksAt = index
        }

        var items: [Item]? {
            if todosAt > tasksAt { return todos }
            return tasksAt >= 0 ? tasks.map(\.item) : nil
        }

        /// One tool step; true when it was one of the task-list tools.
        @discardableResult
        mutating func use(_ name: String, _ input: JSONValue, useID: String?, at index: Int) -> Bool {
            switch name {
            case "TodoWrite": todoWrite(input, at: index)
            case "TaskCreate": create(input, useID: useID, at: index)
            case "TaskUpdate": update(input, at: index)
            default: return false
            }
            return true
        }

        /// A tool's answer, for the id a created task was given.
        mutating func answered(_ part: JSONValue) {
            guard let useID = part["tool_use_id"]?.stringValue else { return }
            let text = part["content"]?.stringValue
                ?? part["content"]?.arrayValue?.compactMap { $0["text"]?.stringValue }.joined(separator: " ") ?? ""
            created(useID: useID, result: text)
        }
    }

    enum Last: Equatable {
        case none
        case prompt
        case injected
        case interrupted
        case toolResult
        case reply(stop: String?, tool: String?)
    }

    /// The summary of one transcript from its last lines (oldest first); nil when they hold
    /// no conversation.
    public static func summarise(lines: [String], id: String, modified: Date, now: Date) -> AISession? {
        var fold = TranscriptFold()
        for line in lines { fold.feed(Data(line.utf8)) }
        return fold.session(id: id, modified: modified, now: now)
    }
}

/// A transcript read line by line, oldest first: what its summary needs and nothing more. It
/// can take more lines later (what was appended), so a growing transcript is never read twice.
public struct TranscriptFold: Sendable {
    var cwd: String?
    var entrypoint: String?
    var title: String?
    var customTitle: String?
    var request: String?
    var answer: String?
    var doing: String?
    var steps: [AISession.Step] = []
    var list = TranscriptSummary.TaskList()
    var last = TranscriptSummary.Last.none
    var seen = false
    var index = 0

    public init() {}

    /// The person's latest request is in what was read.
    public var hasRequest: Bool { request != nil }

    mutating func step(_ text: String, _ at: Date?) {
        steps.append(AISession.Step(at: at, text: text))
        if steps.count > TranscriptSummary.maxSteps { steps.removeFirst(steps.count - TranscriptSummary.maxSteps) }
    }

    /// One line of the transcript.
    public mutating func feed(_ line: Data) {
        index += 1
        guard let entry = JSONValue.quick(line), entry.objectValue != nil else { return }
        let type = entry["type"]?.stringValue
        if type == "ai-title" { title = entry["aiTitle"]?.stringValue ?? title }
        if type == "custom-title" { customTitle = entry["customTitle"]?.stringValue ?? customTitle }
        // A helper's own steps, and the summary written when the context was compacted, are not the session's.
        guard type == "user" || type == "assistant", entry["isSidechain"]?.boolValue != true,
            entry["isCompactSummary"]?.boolValue != true
        else { return }
        seen = true
        if let value = entry["cwd"]?.stringValue { cwd = value }
        if let value = entry["entrypoint"]?.stringValue { entrypoint = value }
        let at = TranscriptSummary.date(entry["timestamp"]?.stringValue)
        let content = entry["message"]?["content"]
        if type == "user" {
            if let parts = content?.arrayValue, parts.contains(where: { $0["type"] == "tool_result" }) {
                for part in parts where part["type"] == "tool_result" { list.answered(part) }
                last = .toolResult
                return
            }
            let text = content?.stringValue
                ?? content?.arrayValue?.compactMap { $0["type"] == "text" ? $0["text"]?.stringValue : nil }.joined(separator: " ") ?? ""
            let origin = entry["origin"]?["kind"]?.stringValue
            if text.hasPrefix("[Request interrupted") {
                last = .interrupted
                step("you stopped it", at)
                return
            }
            let human = origin.map { $0 == "human" }
                ?? (entry["isMeta"]?.boolValue != true && !text.trimmingCharacters(in: .whitespaces).hasPrefix("<"))
            let words = TranscriptSummary.ownWords(text)
            if human && !words.isEmpty {
                request = TranscriptSummary.clip(words)
                last = .prompt
                step("you asked: " + TranscriptSummary.clip(words, 120), at)
            } else if !words.isEmpty || origin != nil {
                last = .injected
            }
        } else {
            var tool: String?
            for part in content?.arrayValue ?? [] {
                switch part["type"]?.stringValue {
                case "text":
                    let text = part["text"]?.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                    if !text.isEmpty {
                        answer = TranscriptSummary.clip(text)
                        step("said: " + TranscriptSummary.clip(text, 120), at)
                    }
                case "tool_use":
                    let name = part["name"]?.stringValue ?? "a tool"
                    let input = part["input"] ?? .object([:])
                    list.use(name, input, useID: part["id"]?.stringValue, at: index)
                    tool = name
                    let phrase = TranscriptSummary.phrase(name, input)
                    doing = phrase
                    step(phrase, at)
                default: break
                }
            }
            // Each block of a reply is its own entry, each with the reply's stop reason.
            last = .reply(stop: entry["message"]?["stop_reason"]?.stringValue, tool: tool)
        }
    }

    /// The summary as of `now`, for a transcript last written at `modified`.
    public func session(id: String, modified: Date, now: Date) -> AISession? {
        guard seen else { return nil }
        typealias T = TranscriptSummary
        let quiet = now.timeIntervalSince(modified)
        let headless = T.place(entrypoint) == "headless"
        var state = AISession.State.working
        var note: String?
        switch last {
        case .reply(_, let tool) where tool == "AskUserQuestion" || tool == "ExitPlanMode":
            state = quiet < T.lostAfter ? .waiting : .finished
            note = tool == "AskUserQuestion" ? "asked you a question" : "showed you a plan to approve"
        case .reply(let stop, _) where stop == "end_turn" || stop == "stop_sequence":
            state = headless || quiet >= T.idleAfter ? .finished : .waiting
            note = state == .waiting ? "its turn ended; it waits for you" : nil
        case .reply:
            if quiet < T.quietAfter {
                state = .working
            } else if quiet < T.lostAfter {
                state = .working
                note = "quiet for \(Int(quiet / 60)) min: a long step, or it may be waiting for your OK"
            } else {
                state = .finished
                note = "stopped in the middle of a step"
            }
        case .interrupted:
            state = quiet >= T.idleAfter ? .finished : .waiting
            note = "you stopped it"
        case .prompt, .injected, .toolResult, .none:
            if quiet < T.thinkingFor {
                state = .working
            } else {
                state = .finished
                note = "no answer since \(Int(quiet / 60)) min ago"
            }
        }
        let items = list.items
        let current = items?.first(where: { $0.status == "in_progress" })
        let project = cwd.map { ($0 as NSString).lastPathComponent } ?? "a project"
        return AISession(
            id: id, project: T.clip(project, 60), title: (customTitle ?? title).map { T.clip($0, 80) }, place: T.place(entrypoint),
            state: state, note: note,
            done: items.map { $0.filter { $0.status == "completed" }.count }, total: items?.count,
            current: current.map { T.clip($0.active ?? $0.text, 120) },
            doing: doing, request: request, answer: answer, updated: modified, steps: steps, task: nil)
    }
}

extension JSONValue {
    /// Parse one line quickly (Foundation's parser: transcripts hold megabytes of JSON, and the
    /// strict decoder the device protocol uses is many times slower on them).
    public static func quick(_ data: Data) -> JSONValue? {
        guard let object = try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]) else { return nil }
        return JSONValue(foundation: object)
    }

    init?(foundation value: Any) {
        switch value {
        case let dictionary as [String: Any]:
            var fields: [String: JSONValue] = [:]
            for (key, item) in dictionary { fields[key] = JSONValue(foundation: item) ?? .null }
            self = .object(fields)
        case let array as [Any]:
            self = .array(array.map { JSONValue(foundation: $0) ?? .null })
        case let string as String:
            self = .string(string)
        case let number as NSNumber:
            self = CFGetTypeID(number) == CFBooleanGetTypeID() ? .bool(number.boolValue) : .number(number.doubleValue)
        case is NSNull:
            self = .null
        default:
            return nil
        }
    }
}

/// The last lines of a file, read from its end: transcripts grow to hundreds of megabytes.
public enum TailReader {
    /// The complete lines in the last `bytes` of the file (all of it when smaller), and
    /// whether that is the whole file.
    public static func lines(_ url: URL, bytes: Int) -> (lines: [String], whole: Bool) {
        let read = tail(url, bytes: bytes)
        return (read.lines.map { String(decoding: $0, as: UTF8.self) }, read.whole)
    }

    /// The complete lines in the last `bytes`, as bytes; whether that is the whole file; and
    /// where the last complete line ends (where to read on from later).
    public static func tail(_ url: URL, bytes: Int) -> (lines: [Data], whole: Bool, end: UInt64) {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return ([], true, 0) }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        let start = size > UInt64(bytes) ? size - UInt64(bytes) : 0
        try? handle.seek(toOffset: start)
        let data = (try? handle.readToEnd()) ?? Data()
        var (lines, used) = split(data)
        if start > 0, !lines.isEmpty { lines.removeFirst() }  // cut in the middle
        return (lines, start == 0, start + UInt64(used))
    }

    /// The complete lines from `offset` on, and where the last of them ends.
    public static func appended(_ url: URL, from offset: UInt64) -> (lines: [Data], end: UInt64) {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return ([], offset) }
        defer { try? handle.close() }
        try? handle.seek(toOffset: offset)
        let data = (try? handle.readToEnd()) ?? Data()
        let (lines, used) = split(data)
        return (lines, offset + UInt64(used))
    }

    /// Complete lines, and how many bytes they take. A last line without its newline counts
    /// when it is already whole JSON; one still being written is left for later.
    static func split(_ data: Data) -> (lines: [Data], used: Int) {
        var lines: [Data] = []
        var lineStart = data.startIndex
        var used = 0
        for index in data.indices where data[index] == 0x0A {
            if index > lineStart { lines.append(data[lineStart..<index]) }
            lineStart = data.index(after: index)
            used = lineStart - data.startIndex
        }
        let rest = data[lineStart...]
        if !rest.isEmpty, (try? JSONSerialization.jsonObject(with: rest, options: [.fragmentsAllowed])) != nil {
            lines.append(rest)
            used = data.count
        }
        return (lines, used)
    }
}

/// `ai_sessions` and `ai_session_detail`.
public final class AISessions: @unchecked Sendable {
    public static let defaultHours = 12
    public static let maxSessions = 8
    /// Read from the end: the last 1 MB, then 4 MB when the person's request is not in it. A
    /// session whose request is further back is told without it: the answer must come in time.
    static let reads = [1 << 20, 4 << 20]

    /// What was read of each transcript, kept while its size and time stay: an unchanged file
    /// is not read again, and a grown one only from where it was left.
    struct Read {
        var size: UInt64
        var modified: Date
        var end: UInt64
        var fold: TranscriptFold
    }

    private let roots: @Sendable () -> [URL]
    private let tasks: CodeTasks?
    private let worktrees: @Sendable () -> URL?
    private let now: @Sendable () -> Date
    private let lock = NSLock()
    private var reads: [String: Read] = [:]

    public init(
        roots: @escaping @Sendable () -> [URL] = { TaskSettings.transcripts() },
        tasks: CodeTasks? = nil,
        worktrees: @escaping @Sendable () -> URL? = { TaskSettings.load()?.worktrees },
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.roots = roots
        self.tasks = tasks
        self.worktrees = worktrees
        self.now = now
    }

    /// The coding agent's transcripts changed in the last `hours`, newest first.
    func transcripts(hours: Int) -> [(url: URL, size: UInt64, modified: Date)] {
        let since = now().addingTimeInterval(-Double(hours) * 3600)
        let fm = FileManager.default
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .isRegularFileKey, .fileSizeKey]
        var found: [(URL, UInt64, Date)] = []
        let folders = roots().flatMap { (try? fm.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)) ?? [] }
        for folder in folders {
            let files = (try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: Array(keys))) ?? []
            for file in files where file.pathExtension == "jsonl" {
                let values = try? file.resourceValues(forKeys: keys)
                guard values?.isRegularFile == true, let modified = values?.contentModificationDate, modified >= since else { continue }
                found.append((file, UInt64(values?.fileSize ?? 0), modified))
            }
        }
        return found.sorted { $0.2 > $1.2 }
    }

    /// One transcript's fold: from what was read before when the file is unchanged or grew.
    func fold(_ url: URL, size: UInt64, modified: Date) -> TranscriptFold {
        let key = url.path
        if let known = lock.locked({ reads[key] }) {
            if known.size == size, known.modified == modified { return known.fold }
            if size > known.size {
                var fold = known.fold
                let more = TailReader.appended(url, from: known.end)
                for line in more.lines { fold.feed(line) }
                lock.locked { reads[key] = Read(size: size, modified: modified, end: more.end, fold: fold) }
                return fold
            }
        }
        var fold = TranscriptFold()
        var end: UInt64 = 0
        for bytes in AISessions.reads {
            fold = TranscriptFold()
            let tail = TailReader.tail(url, bytes: bytes)
            for line in tail.lines { fold.feed(line) }
            end = tail.end
            if tail.whole || fold.hasRequest { break }
        }
        let read = Read(size: size, modified: modified, end: end, fold: fold)
        lock.locked { reads[key] = read }
        return fold
    }

    func summarise(_ url: URL, size: UInt64, modified: Date) -> AISession? {
        let id = url.deletingPathExtension().lastPathComponent
        let fold = fold(url, size: size, modified: modified)
        guard var session = fold.session(id: id, modified: modified, now: now()) else { return nil }
        // A transcript of Ira's own coding task: its worktree is named <repo>-<task id>.
        let roots = worktrees().map { [$0.path, $0.resolvingSymlinksInPath().path] } ?? []
        if let cwd = fold.cwd, roots.contains(where: { cwd.hasPrefix($0 + "/") }) {
            let folder = (cwd as NSString).lastPathComponent
            if let dash = folder.lastIndex(of: "-") {
                let task = String(folder[folder.index(after: dash)...])
                session.task = task
                session.place = "Ira's task \(task)"
                session.project = String(folder[..<dash])
            }
        }
        return session
    }

    /// Ira's own coding tasks that have no transcript here (another agent's, or not begun).
    func ownTasks(excluding: Set<String>) -> [AISession] {
        (tasks?.jobs() ?? []).filter { !excluding.contains($0.id) }.map { job in
            let state: AISession.State = job.status == "waiting" ? .waiting : ["starting", "running"].contains(job.status) ? .working : .finished
            var session = AISession(
                id: job.id, project: job.repo.name, title: nil, place: "", state: state,
                note: state == .finished ? job.status : nil, done: nil, total: nil, current: nil,
                doing: job.progress.last.map { TranscriptSummary.clip($0, 120) },
                request: job.instruction.isEmpty ? nil : TranscriptSummary.clip(job.instruction),
                answer: job.result.isEmpty ? nil : TranscriptSummary.clip(job.result),
                updated: job.finished ?? job.started,
                steps: job.progress.map { AISession.Step(at: nil, text: TranscriptSummary.clip($0, 120)) }, task: job.id)
            AISessions.mark(&session, job)
            return session
        }
    }

    /// One of Ira's tasks: its name, and whether the person can talk to it now.
    static func mark(_ session: inout AISession, _ job: CodeTasks.Job) {
        session.task = job.id
        session.talk = job.chat && CodeTasks.live.contains(job.status)
        session.place = (job.chat ? "Ira's chat task " : "Ira's task ") + (job.label.isEmpty ? job.id : job.label)
        if job.status == "waiting" {
            session.state = .waiting
            session.note = "waiting for your next message"
        }
    }

    public func sessions(hours: Int = defaultHours) async -> [AISession] {
        let files = Array(transcripts(hours: hours).prefix(AISessions.maxSessions * 2))
        // Side by side: one big transcript must not hold up the others.
        let found = await withTaskGroup(of: AISession?.self) { group in
            for file in files {
                group.addTask { self.summarise(file.url, size: file.size, modified: file.modified) }
            }
            var all: [AISession] = []
            for await session in group { if let session { all.append(session) } }
            return all
        }
        // Forget what was read of transcripts no longer listed.
        let listed = Set(files.map(\.url.path))
        lock.locked { reads = reads.filter { listed.contains($0.key) } }
        // Ira's own tasks among the transcripts: named, and marked when they can be talked to.
        let jobs = Dictionary((tasks?.jobs() ?? []).map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let named = found.map { session -> AISession in
            guard let id = session.task, let job = jobs[id] else { return session }
            var marked = session
            AISessions.mark(&marked, job)
            return marked
        }
        let mine = Set(named.compactMap(\.task))
        // The ones the person can talk to come first, then the newest.
        let all = (named + ownTasks(excluding: mine)).sorted { ($0.talk ? 1 : 0, $0.updated) > ($1.talk ? 1 : 0, $1.updated) }
        return Array(all.prefix(AISessions.maxSessions))
    }

    // MARK: The tools

    public func list(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["hours"])
        let hours = try args.number("hours", 1...48) ?? AISessions.defaultHours
        let all = await sessions(hours: hours)
        let now = now()
        let lines = all.map { AISessions.sentence($0, now: now) }
        var summary = all.isEmpty
            ? "No AI coding sessions on this Mac in the last \(hours) hours."
            : "\(all.count) AI session\(all.count == 1 ? "" : "s") on this Mac in the last \(hours) hours. " + lines.joined(separator: " ")
        if roots().isEmpty {
            summary += " (Ira reads a coding agent's own sessions once its transcripts folder is listed in tasks.json.)"
        }
        return [
            "sessions": .array(all.map { AISessions.view($0, now: now, steps: false) }),
            "summary": .string(summary),
            "control": .string(AISessions.control),
        ]
    }

    public func detail(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id"])
        let id = try args.required("id", limit: 80, what: "which session (its id from ai_sessions)")
        let all = await sessions(hours: 48)
        guard let session = all.first(where: { $0.id == id }) ?? all.first(where: { $0.id.hasPrefix(id) }) else {
            throw ToolFailure("no AI session with that id on this Mac in the last 48 hours")
        }
        let now = now()
        var view = AISessions.view(session, now: now, steps: true)
        if case .object(var fields) = view {
            let steps = session.steps.map(\.text).joined(separator: "; ")
            fields["summary"] = .string(AISessions.sentence(session, now: now) + (steps.isEmpty ? "" : " Last steps: \(steps)."))
            fields["control"] = .string(
                session.talk ? "Ira's chat task: talk to it with code_task_say, by its name."
                    : session.task == nil ? AISessions.control : "Ira started this task: code_task_status and code_task_stop work on it.")
            view = .object(fields)
        }
        return view
    }

    static let control =
        "Ira's own chat tasks (talk: true) can be talked to from the phone with code_task_say, by name. Every other session is read-only here: to message one, the person uses the agent's own remote control (its mobile app); to stop it, Esc in VS Code's panel or Ctrl-C in a terminal. Ira never sends to or stops a session it did not start."

    static func ago(_ date: Date, now: Date) -> String {
        let minutes = Int(now.timeIntervalSince(date) / 60)
        if minutes < 1 { return "just now" }
        if minutes < 60 { return "\(minutes) min ago" }
        return "\(minutes / 60) h \(minutes % 60) min ago"
    }

    /// One sentence: "ira (VS Code): working, 3 of 7 done, on: writing tests; last step: read Drop.kt."
    static func sentence(_ session: AISession, now: Date) -> String {
        var parts = ["\(session.project) (\(session.place)): \(session.state == .waiting ? "waiting for you" : session.state.rawValue)"]
        parts.append(session.talk ? "you can talk to it from your phone" : session.task == nil ? "read-only here" : "Ira's task")
        if let note = session.note, session.state != .working || note.hasPrefix("quiet") { parts.append(note) }
        if let done = session.done, let total = session.total, total > 0 { parts.append("\(done) of \(total) done") }
        if let current = session.current { parts.append("on: \(current)") }
        if session.state == .working, let doing = session.doing { parts.append("last step: \(doing)") }
        if let request = session.request { parts.append("asked: “\(AgentOutput.short(request, 100))”") }
        parts.append("updated \(ago(session.updated, now: now))")
        return parts.joined(separator: ", ") + "."
    }

    static func view(_ session: AISession, now: Date, steps: Bool) -> JSONValue {
        var fields: [String: JSONValue] = [
            "id": .string(session.id), "project": .string(session.project), "place": .string(session.place),
            "state": .string(session.state.rawValue), "updated": .string(ISO8601DateFormatter().string(from: session.updated)),
            "updatedAgo": .string(ago(session.updated, now: now)), "startedByIra": .bool(session.task != nil),
            "talk": .bool(session.talk),
        ]
        func put(_ key: String, _ value: String?) { if let value { fields[key] = .string(value) } }
        put("title", session.title)
        put("note", session.note)
        put("current", session.current)
        put("doing", session.doing)
        put("request", session.request)
        put("answer", session.answer)
        put("task", session.task)
        if let done = session.done, let total = session.total {
            fields["done"] = .number(Double(done))
            fields["total"] = .number(Double(total))
        }
        if steps {
            let time = DateFormatter()
            time.dateFormat = "HH:mm"
            fields["steps"] = .array(session.steps.map { step in
                ["at": .string(step.at.map { time.string(from: $0) } ?? ""), "text": .string(step.text)]
            })
        }
        return .object(fields)
    }
}


/// A running coding agent's task list, from its stream-json output: progress counted in steps
/// ("4 of 7 done: tests written; now fixing the total"), not only in minutes.
public struct StepTracker: Sendable {
    private var list = TranscriptSummary.TaskList()
    private var lines = 0
    public private(set) var done = 0
    public private(set) var total = 0
    /// The item in progress.
    public private(set) var current: String?
    /// The item done last.
    public private(set) var finished: String?

    public init() {}

    /// The agent keeps a task list: report steps rather than minutes.
    public var counting: Bool { total > 0 }

    /// One line of output; true when another item was done.
    public mutating func feed(_ line: String) -> Bool {
        lines += 1
        guard line.contains("\"type\""), let entry = JSONValue.quick(Data(line.utf8)) else { return false }
        let parts = entry["message"]?["content"]?.arrayValue ?? []
        var changed = false
        for part in parts {
            if part["type"] == "tool_result" { list.answered(part) }
            if part["type"] == "tool_use", let name = part["name"]?.stringValue {
                changed = list.use(name, part["input"] ?? .object([:]), useID: part["id"]?.stringValue, at: lines) || changed
            }
        }
        guard changed, let items = list.items else { return false }
        let before = done
        let completed = items.filter { $0.status == "completed" }
        done = completed.count
        total = items.count
        current = items.first(where: { $0.status == "in_progress" }).map { TranscriptSummary.clip($0.active ?? $0.text, 120) }
        if done > before, let last = completed.last { finished = TranscriptSummary.clip(last.text, 120) }
        return done > before
    }

    /// "4 of 7 done: tests written; now fixing the total."
    public var sentence: String {
        var text = "\(done) of \(total) done"
        if let finished { text += ": \(finished)" }
        if let current { text += "; now \(current.prefix(1).lowercased() + current.dropFirst())" }
        return text + "."
    }
}
