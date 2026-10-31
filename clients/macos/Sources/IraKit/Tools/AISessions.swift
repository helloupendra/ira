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
        var cwd: String?
        var entrypoint: String?
        var title: String?
        var customTitle: String?
        var request: String?
        var answer: String?
        var doing: String?
        var steps: [AISession.Step] = []
        var list = TaskList()
        var last = Last.none
        var seen = false

        func step(_ text: String, _ at: Date?) {
            steps.append(AISession.Step(at: at, text: text))
            if steps.count > maxSteps { steps.removeFirst(steps.count - maxSteps) }
        }

        for (index, line) in lines.enumerated() {
            guard line.contains("\"type\""), let entry = JSONValue.parse(line), entry.objectValue != nil else { continue }
            let type = entry["type"]?.stringValue
            if type == "ai-title" { title = entry["aiTitle"]?.stringValue ?? title }
            if type == "custom-title" { customTitle = entry["customTitle"]?.stringValue ?? customTitle }
            // A helper's own steps, and the summary written when the context was compacted, are not the session's.
            guard type == "user" || type == "assistant", entry["isSidechain"]?.boolValue != true,
                entry["isCompactSummary"]?.boolValue != true
            else { continue }
            seen = true
            if let value = entry["cwd"]?.stringValue { cwd = value }
            if let value = entry["entrypoint"]?.stringValue { entrypoint = value }
            let at = date(entry["timestamp"]?.stringValue)
            let content = entry["message"]?["content"]
            if type == "user" {
                if let parts = content?.arrayValue, parts.contains(where: { $0["type"] == "tool_result" }) {
                    for part in parts where part["type"] == "tool_result" {
                        guard let useID = part["tool_use_id"]?.stringValue else { continue }
                        let text = part["content"]?.stringValue
                            ?? part["content"]?.arrayValue?.compactMap { $0["text"]?.stringValue }.joined(separator: " ") ?? ""
                        list.created(useID: useID, result: text)
                    }
                    last = .toolResult
                    continue
                }
                let text = content?.stringValue
                    ?? content?.arrayValue?.compactMap { $0["type"] == "text" ? $0["text"]?.stringValue : nil }.joined(separator: " ") ?? ""
                let origin = entry["origin"]?["kind"]?.stringValue
                if text.hasPrefix("[Request interrupted") {
                    last = .interrupted
                    step("you stopped it", at)
                    continue
                }
                let human = origin.map { $0 == "human" }
                    ?? (entry["isMeta"]?.boolValue != true && !text.trimmingCharacters(in: .whitespaces).hasPrefix("<"))
                let words = ownWords(text)
                if human && !words.isEmpty {
                    request = clip(words)
                    last = .prompt
                    step("you asked: " + clip(words, 120), at)
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
                            answer = clip(text)
                            step("said: " + clip(text, 120), at)
                        }
                    case "tool_use":
                        let name = part["name"]?.stringValue ?? "a tool"
                        let input = part["input"] ?? .object([:])
                        switch name {
                        case "TodoWrite": list.todoWrite(input, at: index)
                        case "TaskCreate": list.create(input, useID: part["id"]?.stringValue, at: index)
                        case "TaskUpdate": list.update(input, at: index)
                        default: break
                        }
                        tool = name
                        let phrase = phrase(name, input)
                        doing = phrase
                        step(phrase, at)
                    default: break
                    }
                }
                // Each block of a reply is its own entry, each with the reply's stop reason.
                last = .reply(stop: entry["message"]?["stop_reason"]?.stringValue, tool: tool)
            }
        }
        guard seen else { return nil }

        let quiet = now.timeIntervalSince(modified)
        let headless = place(entrypoint) == "headless"
        var state = AISession.State.working
        var note: String?
        switch last {
        case .reply(_, let tool) where tool == "AskUserQuestion" || tool == "ExitPlanMode":
            state = quiet < lostAfter ? .waiting : .finished
            note = tool == "AskUserQuestion" ? "asked you a question" : "showed you a plan to approve"
        case .reply(let stop, _) where stop == "end_turn" || stop == "stop_sequence":
            state = headless || quiet >= idleAfter ? .finished : .waiting
            note = state == .waiting ? "its turn ended; it waits for you" : nil
        case .reply:
            if quiet < quietAfter {
                state = .working
            } else if quiet < lostAfter {
                state = .working
                note = "quiet for \(Int(quiet / 60)) min: a long step, or it may be waiting for your OK"
            } else {
                state = .finished
                note = "stopped in the middle of a step"
            }
        case .interrupted:
            state = quiet >= idleAfter ? .finished : .waiting
            note = "you stopped it"
        case .prompt, .injected, .toolResult, .none:
            if quiet < thinkingFor {
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
            id: id, project: clip(project, 60), title: (customTitle ?? title).map { clip($0, 80) }, place: place(entrypoint),
            state: state, note: note,
            done: items.map { $0.filter { $0.status == "completed" }.count }, total: items?.count,
            current: current.map { clip($0.active ?? $0.text, 120) },
            doing: doing, request: request, answer: answer, updated: modified, steps: steps, task: nil)
    }
}

/// The last lines of a file, read from its end: transcripts grow to hundreds of megabytes.
public enum TailReader {
    /// The complete lines in the last `bytes` of the file (all of it when smaller), and
    /// whether that is the whole file.
    public static func lines(_ url: URL, bytes: Int) -> (lines: [String], whole: Bool) {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return ([], true) }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        let start = size > UInt64(bytes) ? size - UInt64(bytes) : 0
        try? handle.seek(toOffset: start)
        let data = (try? handle.readToEnd()) ?? Data()
        var lines = String(decoding: data, as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
        if start > 0, !lines.isEmpty { lines.removeFirst() }  // cut in the middle
        return (lines, start == 0)
    }
}

/// `ai_sessions` and `ai_session_detail`.
public final class AISessions: @unchecked Sendable {
    public static let defaultHours = 12
    public static let maxSessions = 8
    /// Read from the end in growing pieces until the person's last request is in view.
    static let reads = [1 << 20, 4 << 20, 16 << 20]

    private let roots: @Sendable () -> [URL]
    private let tasks: CodeTasks?
    private let worktrees: @Sendable () -> URL?
    private let now: @Sendable () -> Date

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
    func transcripts(hours: Int) -> [(url: URL, modified: Date)] {
        let since = now().addingTimeInterval(-Double(hours) * 3600)
        let fm = FileManager.default
        var found: [(URL, Date)] = []
        let folders = roots().flatMap { (try? fm.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)) ?? [] }
        for folder in folders {
            let files = (try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey, .isRegularFileKey])) ?? []
            for file in files where file.pathExtension == "jsonl" {
                let values = try? file.resourceValues(forKeys: [.contentModificationDateKey, .isRegularFileKey])
                guard values?.isRegularFile == true, let modified = values?.contentModificationDate, modified >= since else { continue }
                found.append((file, modified))
            }
        }
        return found.sorted { $0.1 > $1.1 }
    }

    func summarise(_ url: URL, modified: Date) -> AISession? {
        let id = url.deletingPathExtension().lastPathComponent
        var summary: AISession?
        for bytes in AISessions.reads {
            let (lines, whole) = TailReader.lines(url, bytes: bytes)
            summary = TranscriptSummary.summarise(lines: lines, id: id, modified: modified, now: now())
            if whole || summary?.request != nil { break }
        }
        guard var session = summary else { return nil }
        // A transcript of Ira's own coding task: its worktree is named <repo>-<task id>.
        let roots = worktrees().map { [$0.path, $0.resolvingSymlinksInPath().path] } ?? []
        if let cwd = TranscriptSummary.cwd(of: url), roots.contains(where: { cwd.hasPrefix($0 + "/") }) {
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
            let state: AISession.State = ["starting", "running"].contains(job.status) ? .working : .finished
            return AISession(
                id: job.id, project: job.repo.name, title: nil, place: "Ira's task \(job.id)", state: state,
                note: state == .finished ? job.status : nil, done: nil, total: nil, current: nil,
                doing: job.progress.last.map { TranscriptSummary.clip($0, 120) },
                request: TranscriptSummary.clip(job.instruction), answer: job.result.isEmpty ? nil : TranscriptSummary.clip(job.result),
                updated: job.finished ?? job.started,
                steps: job.progress.map { AISession.Step(at: nil, text: TranscriptSummary.clip($0, 120)) }, task: job.id)
        }
    }

    public func sessions(hours: Int = defaultHours) -> [AISession] {
        let found = transcripts(hours: hours).prefix(AISessions.maxSessions * 2).compactMap { summarise($0.url, modified: $0.modified) }
        let mine = Set(found.compactMap(\.task))
        return Array((found + ownTasks(excluding: mine)).sorted { $0.updated > $1.updated }.prefix(AISessions.maxSessions))
    }

    // MARK: The tools

    public func list(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["hours"])
        let hours = try args.number("hours", 1...48) ?? AISessions.defaultHours
        let all = sessions(hours: hours)
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
        let all = sessions(hours: 48)
        guard let session = all.first(where: { $0.id == id }) ?? all.first(where: { $0.id.hasPrefix(id) }) else {
            throw ToolFailure("no AI session with that id on this Mac in the last 48 hours")
        }
        let now = now()
        var view = AISessions.view(session, now: now, steps: true)
        if case .object(var fields) = view {
            let steps = session.steps.map(\.text).joined(separator: "; ")
            fields["summary"] = .string(AISessions.sentence(session, now: now) + (steps.isEmpty ? "" : " Last steps: \(steps)."))
            fields["control"] = .string(session.task == nil ? AISessions.control : "Ira started this task: code_task_status and code_task_stop work on it.")
            view = .object(fields)
        }
        return view
    }

    static let control =
        "Ira only reads these sessions. To stop or steer one Ira did not start, the person does it where it runs (Esc in VS Code's panel, Ctrl-C in a terminal). Ira's own tasks: code_task_status and code_task_stop."

    static func ago(_ date: Date, now: Date) -> String {
        let minutes = Int(now.timeIntervalSince(date) / 60)
        if minutes < 1 { return "just now" }
        if minutes < 60 { return "\(minutes) min ago" }
        return "\(minutes / 60) h \(minutes % 60) min ago"
    }

    /// One sentence: "ira (VS Code): working, 3 of 7 done, on: writing tests; last step: read Drop.kt."
    static func sentence(_ session: AISession, now: Date) -> String {
        var parts = ["\(session.project) (\(session.place)): \(session.state == .waiting ? "waiting for you" : session.state.rawValue)"]
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

extension TranscriptSummary {
    /// The working folder a transcript names, from its last lines.
    static func cwd(of url: URL) -> String? {
        TailReader.lines(url, bytes: 256 << 10).lines.reversed().lazy.compactMap { line -> String? in
            guard line.contains("\"cwd\"") else { return nil }
            return JSONValue.parse(line)?["cwd"]?.stringValue
        }.first
    }
}
