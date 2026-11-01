import Foundation

/// Coding tasks: a coding agent at work in a NEW git worktree of a repository
/// the person allowed, with VS Code open on it so they can watch.
///
/// Everything about it is set on this Mac, in
/// `~/Library/Application Support/Ira/tasks.json`, never in a repository or on
/// the server:
///
/// ```json
/// {
///   "agents": {
///     "main": {"command": ["/path/to/agent", "-p", "{prompt}", "--output-format", "stream-json"],
///              "resume": ["--resume", "{session}"]},
///     "other": {"command": ["/path/to/other-agent", "-p", "{prompt}"]}
///   },
///   "default_agent": "main",
///   "repos": {
///     "shop": {"path": "~/code/shop", "test": "pytest -q"},
///     "site": {"path": "~/code/site", "protected": true}
///   },
///   "worktrees": "~/ira-tasks",
///   "writable": ["~/.agent-state"],
///   "minutes": 60,
///   "vscode": {"open": true, "promptURI": "vscode://publisher.extension/open?prompt={prompt}"}
/// }
/// ```
///
/// A single `"command": [...]` still works: it is the agent named "default".
///
/// The agent runs in macOS's sandbox (`sandbox-exec`), which lets it write only
/// to its worktree, the repository's `.git`, temporary folders and the
/// `writable` list, and its git refuses to push. `code_task_push`, which Ira
/// runs only after the person's PIN, pushes the task's own branch: never
/// `main`, `master` or the remote's default branch, never with `--force`, and
/// in a `protected` repository (one that deploys when its main branch moves)
/// only a task branch. These stop accidents and a confused agent; they are not
/// a wall against hostile code.
public struct TaskSettings: Equatable, Sendable {
    public struct Repo: Equatable, Sendable {
        public let name: String
        public let path: URL
        public let test: String?
        public let protected: Bool
    }

    /// A coding agent this Mac may run.
    public struct Agent: Equatable, Sendable {
        public let name: String
        /// Its command line; `{prompt}` is replaced by the task.
        public let command: [String]
        /// What continues one of its earlier sessions; `{session}` is the session's id.
        public let resume: [String]?

        public init(name: String, command: [String], resume: [String]? = nil) {
            self.name = name
            self.command = command
            self.resume = resume
        }

        /// It reads stream-json on its stdin (`--input-format stream-json`): Ira sends it the
        /// task that way, and the person's words while it works.
        public var streamsInput: Bool {
            command.contains("--input-format=stream-json")
                || zip(command, command.dropFirst()).contains { $0 == "--input-format" && $1 == "stream-json" }
        }

        /// It can continue an earlier session: a pause loses nothing.
        public var resumes: Bool { !(resume ?? []).isEmpty }
    }

    public var command: [String]
    public var repos: [String: Repo]
    public var worktrees: URL
    public var writable: [URL]
    public var minutes: Double
    public var sandbox: Bool
    public var openVSCode: Bool
    public var promptURI: String?
    /// The agents by name; empty means `command` alone, as the agent "default".
    public var agents: [String: Agent] = [:]
    public var defaultAgent = "default"

    /// The agent `name` (the default one when nil).
    public func agent(_ name: String? = nil) -> Agent? {
        let wanted = name ?? defaultAgent
        if let agent = agents[wanted] { return agent }
        guard agents.isEmpty, wanted == "default", !command.isEmpty else { return nil }
        return Agent(name: "default", command: command)
    }

    public var agentNames: [String] { agents.isEmpty ? ["default"] : agents.keys.sorted() }

    public static var defaultPath: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Ira/tasks.json")
    }

    static func expand(_ path: String, home: URL) -> URL {
        PathPolicy.expand(path, home: home) ?? URL(fileURLWithPath: path)
    }

    static func validName(_ name: String) -> Bool {
        name.range(of: #"^[A-Za-z0-9._-]{1,60}$"#, options: .regularExpression) != nil
    }

    /// The settings in a tasks.json; nil when tasks are not set up on this Mac.
    public static func parse(_ data: Data, home: URL = FileManager.default.homeDirectoryForCurrentUser) -> TaskSettings? {
        guard let raw = JSONValue.parse(data), raw.objectValue != nil else { return nil }
        var repos: [String: Repo] = [:]
        for (name, entry) in raw["repos"]?.objectValue ?? [:] {
            let path = entry.stringValue ?? entry["path"]?.stringValue
            guard let path, !path.isEmpty, validName(name) else { continue }
            repos[name] = Repo(
                name: name, path: expand(path, home: home), test: entry["test"]?.stringValue,
                protected: entry["protected"]?.boolValue ?? false)
        }
        var agents: [String: Agent] = [:]
        for (name, entry) in raw["agents"]?.objectValue ?? [:] {
            let command = (entry.arrayValue ?? entry["command"]?.arrayValue ?? []).compactMap(\.stringValue)
            guard !command.isEmpty, validName(name) else { continue }
            agents[name] = Agent(name: name, command: command, resume: entry["resume"]?.arrayValue?.compactMap(\.stringValue))
        }
        let single = (raw["command"]?.arrayValue ?? []).compactMap(\.stringValue)
        if !single.isEmpty, agents["default"] == nil {
            agents["default"] = Agent(name: "default", command: single, resume: raw["resume"]?.arrayValue?.compactMap(\.stringValue))
        }
        let named = raw["default_agent"]?.stringValue.flatMap { agents[$0] == nil ? nil : $0 }
        guard let chosen = named ?? (agents["default"] != nil ? "default" : agents.keys.sorted().first),
            let main = agents[chosen], !repos.isEmpty
        else { return nil }
        let vscode = raw["vscode"]
        return TaskSettings(
            command: main.command, repos: repos,
            worktrees: expand(raw["worktrees"]?.stringValue ?? "~/ira-tasks", home: home),
            writable: (raw["writable"]?.arrayValue ?? []).compactMap(\.stringValue).map { expand($0, home: home) },
            minutes: raw["minutes"]?.doubleValue ?? 60,
            sandbox: raw["sandbox"]?.boolValue ?? true,
            openVSCode: vscode?["open"]?.boolValue ?? true,
            promptURI: vscode?["promptURI"]?.stringValue,
            agents: agents, defaultAgent: chosen)
    }

    public static func load(from url: URL = defaultPath) -> TaskSettings? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return parse(data)
    }

    /// The folders where coding agents keep their transcripts, one folder per project
    /// (`"transcripts": ["~/.agent/projects"]`), for `ai_sessions`. Read even when coding
    /// tasks are not set up.
    public static func transcripts(from url: URL = defaultPath, home: URL = FileManager.default.homeDirectoryForCurrentUser) -> [URL] {
        guard let data = try? Data(contentsOf: url), let raw = JSONValue.parse(data) else { return [] }
        return (raw["transcripts"]?.arrayValue ?? []).compactMap(\.stringValue).filter { !$0.isEmpty }.map { expand($0, home: home) }
    }
}

/// Which branches a task may push. Tested on its own, because a mistake here
/// could put unreviewed code on a branch that deploys.
public enum PushGuard {
    /// Never pushed, in any repository.
    public static let neverPushed: Set<String> = ["main", "master"]
    /// Also never pushed in a protected repository.
    public static let protectedNames: Set<String> = [
        "main", "master", "production", "prod", "release", "deploy", "live", "stable", "trunk", "develop", "gh-pages",
    ]
    public static let taskPrefix = "ira/task-"

    /// Why `branch` may not be pushed, or nil. `defaultBranch` is the remote's
    /// (from origin/HEAD), when known.
    public static func refusal(branch: String, defaultBranch: String?, protected: Bool) -> String? {
        let name = branch.trimmingCharacters(in: .whitespaces)
        if name.isEmpty || name.hasPrefix("-") || name.contains("..") || name.contains(":") || name.contains(" ") {
            return "that is not a branch Ira pushes"
        }
        if neverPushed.contains(name.lowercased()) || name.hasPrefix("refs/") {
            return "Ira never pushes \(name)"
        }
        if let defaultBranch, name == defaultBranch {
            return "Ira never pushes the default branch (\(defaultBranch))"
        }
        if protected {
            if protectedNames.contains(name.lowercased()) {
                return "this repository is protected: Ira never pushes \(name)"
            }
            if !name.hasPrefix(taskPrefix) {
                return "this repository is protected: Ira pushes only its own task branches"
            }
        }
        return nil
    }

    /// The push command: the branch to the same name, never forced.
    public static func pushArguments(branch: String) -> [String] {
        ["push", "--set-upstream", "origin", "refs/heads/\(branch):refs/heads/\(branch)"]
    }
}

/// A coding agent's progress, from one line of its stream-json output.
public enum AgentOutput {
    public static func short(_ text: String, _ limit: Int = 240) -> String {
        let joined = text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return joined.count <= limit ? joined : String(joined.prefix(limit - 1)) + "…"
    }

    /// The steps in one line of the agent's output, as phrases ("edited Invoice.swift").
    public static func steps(_ line: String) -> [String] {
        guard line.contains("tool_use"), let item = JSONValue.quick(Data(line.utf8)), item["type"] == "assistant" else { return [] }
        return (item["message"]?["content"]?.arrayValue ?? []).compactMap { part in
            guard part["type"] == "tool_use", let name = part["name"]?.stringValue else { return nil }
            return TranscriptSummary.phrase(name, part["input"] ?? .object([:]))
        }
    }

    /// The agent's own session id, which a stream-json line carries.
    public static func session(_ line: String) -> String? {
        guard line.contains("session_id"), let item = JSONValue.quick(Data(line.utf8)) else { return nil }
        return item["session_id"]?.stringValue.flatMap { $0.isEmpty ? nil : String($0.prefix(100)) }
    }

    /// (a progress line, the final result) from one line.
    public static func progress(_ line: String) -> (String?, JSONValue?) {
        let line = line.trimmingCharacters(in: .whitespaces)
        guard !line.isEmpty else { return (nil, nil) }
        guard let item = JSONValue.quick(Data(line.utf8)) else { return (short(line), nil) }
        guard item.objectValue != nil else { return (nil, nil) }
        if item["type"] == "result" { return (nil, item) }
        if item["type"] == "assistant", let parts = item["message"]?["content"]?.arrayValue {
            let text = parts.compactMap { $0["text"]?.stringValue }.filter { !$0.isEmpty }.joined(separator: " ")
            if !text.isEmpty { return (short(text), nil) }
            let tools = parts.compactMap { $0["name"]?.stringValue }
            if !tools.isEmpty { return ("using \(tools.joined(separator: ", "))", nil) }
        }
        return (nil, nil)
    }
}

/// Runs the coding tasks of this Mac. Events (done, failed) go out through `announce`.
public final class CodeTasks: @unchecked Sendable {
    public typealias Announce = @Sendable (_ event: String, _ title: String, _ text: String, _ data: JSONValue) -> Void

    public static let maxRunning = 2
    /// A long task says how it is going: first after 5 minutes, then every 10.
    public static let progressAfter: Double = 300
    public static let progressEvery: Double = 600
    /// Steps done close together are said together: at most one a minute, and the last at once.
    public static let stepSpacing: Double = 60
    public static let maxInstruction = 4000
    public static let maxFiles = 50
    /// How long code_task_say waits for the agent's reply (the server waits 25 s for a tool);
    /// a later reply goes out as a task_reply event.
    public static let replyWait: Double = 20
    /// A chat task with nothing said for this long pauses (its session kept for a resume).
    public static let chatIdle: Double = 1800
    /// A reply as the person hears it: secret-masked, cut to this length.
    public static let maxReply = 800
    /// Running, or a chat task waiting for the person's next message: its agent is alive.
    public static let live: Set<String> = ["starting", "running", "waiting"]
    static let noPushURL = "ira-task-cannot-push:"
    static let sandboxExec = "/usr/bin/sandbox-exec"

    static let prompt = """
        You are doing a task for the person who owns this Mac, in this folder: a new git worktree of \
        the repository "{repo}", on the branch {branch}. Rules: work only in this folder. Do not push, \
        merge, deploy or publish anything. Do not delete or change files outside this folder. Do not \
        install anything from the network unless the task says so. Commit your work on this branch if \
        that helps. When you finish, end with a short summary: what you changed, and how you checked it.

        The task: {instruction}
        """

    /// A chat task's first words when the person gave no task yet.
    static let chatOpening = "The person will message you here, one message at a time. Say hello in one short line and wait for their first message."

    static let profile = """
        (version 1)
        (allow default)
        (deny file-write* (subpath (param "HOME")) (subpath "/opt/homebrew") (subpath "/usr/local"))
        (allow file-write*
          (subpath (param "WORKTREE"))
          (subpath (param "GITDIR"))
          (subpath "/private/tmp")
          (subpath "/private/var/folders")
          (subpath (string-append (param "HOME") "/Library/Caches"))
        {extra})
        """

    public struct Job: Sendable {
        public let id: String
        public let repo: TaskSettings.Repo
        public let instruction: String
        public let branch: String
        public let worktree: URL
        public let base: String
        public let started: Date
        public var status = "starting"  // starting, running, waiting (a chat task, between messages), paused, done, failed, stopped
        public var finished: Date?
        public var progress: [String] = []
        public var result = ""
        public var error = ""
        public var files: [String] = []
        public var tests = "not run"
        /// Which agent works on it.
        public var agent = "default"
        /// The agent's own session id, from its output: what a resume continues.
        public var session: String?
        /// Its task list's progress, when the agent keeps one.
        public var done: Int?
        public var total: Int?
        public var current: String?
        /// Messages sent on a stream-json agent's stdin, and its results so far: its input
        /// closes when every message has its answer, so it can finish.
        var sent = 0
        var answered = 0
        /// Which run of its agent is current: a resume starts another, and the one it
        /// replaced (still ending) must not touch the task.
        var runs = 0
        /// The name the person can say: "shop · main" (the repository and the agent).
        public var label = ""
        /// A chat task: its agent stays on between messages, and each reply comes back.
        public var chat = false
        /// What the agent did since the person's last message, for its reply.
        var stepsSince: [String] = []
        /// code_task_say is waiting for the reply to its message; one that came before it
        /// was ready to hear it is kept in `early`.
        var awaiting = false
        var early: String?

        func view() -> JSONValue {
            [
                "id": .string(id), "label": .string(label), "chat": .bool(chat),
                "repo": .string(repo.name), "branch": .string(branch), "status": .string(status),
                "instruction": .string(String(instruction.prefix(200))), "worktree": .string(worktree.path),
                "progress": .array(progress.map { .string($0) }), "summary": .string(String(result.prefix(2000))),
                "error": .string(error), "files": .array(files.map { .string($0) }), "tests": .string(tests),
                "agent": .string(agent), "steps": done.flatMap { done in total.map { .string("\(done) of \($0) done") } } ?? .null,
                "current": current.map { .string($0) } ?? .null,
            ]
        }
    }

    private let settings: @Sendable () -> TaskSettings?
    public var announce: Announce
    private let openVSCode: @Sendable (URL) async -> Void
    private let lock = NSLock()
    private var tasks: [String: Job] = [:]
    private var commands: [String: Command] = [:]
    /// code_task_say waiting for a task's next reply, by task id (with a token: only its own
    /// timer may end it).
    private var waiters: [String: (token: UUID, reply: CheckedContinuation<String?, Never>)] = [:]
    private var idlers: [String: Task<Void, Never>] = [:]
    private let hooks: URL
    private let stepSpacing: Double
    private let replyWait: Double
    private let chatIdle: Double

    public init(
        settings: @escaping @Sendable () -> TaskSettings? = { TaskSettings.load() },
        openVSCode: @escaping @Sendable (URL) async -> Void = { try? await AppTools.openInVSCode($0) },
        stepSpacing: Double = CodeTasks.stepSpacing,
        replyWait: Double = CodeTasks.replyWait,
        chatIdle: Double = CodeTasks.chatIdle,
        announce: @escaping Announce = { _, _, _, _ in }
    ) {
        self.settings = settings
        self.stepSpacing = stepSpacing
        self.replyWait = replyWait
        self.chatIdle = chatIdle
        self.openVSCode = openVSCode
        self.announce = announce
        hooks = FileManager.default.temporaryDirectory.appendingPathComponent("ira-task-hooks-\(getpid())")
        try? FileManager.default.createDirectory(at: hooks, withIntermediateDirectories: true)
        let hook = hooks.appendingPathComponent("pre-push")
        try? "#!/bin/sh\necho 'Ira tasks never push: the person pushes after their PIN.' >&2\nexit 1\n"
            .write(to: hook, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: hook.path)
    }

    public var configured: Bool { settings() != nil }

    /// This Mac's tasks, newest first.
    public func jobs() -> [Job] {
        lock.locked { tasks.values.sorted { $0.started > $1.started } }
    }

    private func current() throws -> TaskSettings {
        guard let settings = settings() else {
            throw ToolFailure("coding tasks are not set up on this Mac (see Ira for Mac's guide: tasks.json)")
        }
        return settings
    }

    private func task(_ args: ToolArgs) throws -> Job {
        try find(try args.required("id", limit: 80, what: "which task: its id, its name (such as \"shop · main\"), or \"last\""))
    }

    /// Words as names compare: lower case, no accents, no punctuation.
    static func fold(_ text: String) -> String {
        String(text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
            .map { $0.isLetter || $0.isNumber ? $0 : " " })
            .split(separator: " ").joined(separator: " ")
    }

    static let lastWords: Set<String> = ["last", "the last one", "last one", "latest", "the latest", "the last task", "that one", "it"]

    /// A task by its id, its name ("shop · main", or part of it such as "shop"), or "last": a
    /// running or paused one before a finished one, then the newest.
    public func find(_ wanted: String) throws -> Job {
        let all = jobs()
        if let exact = all.first(where: { $0.id == wanted }) { return exact }
        func best(_ found: [Job]) -> Job? {
            found.first { CodeTasks.live.contains($0.status) } ?? found.first { $0.status == "paused" } ?? found.first
        }
        let key = CodeTasks.fold(wanted)
        if CodeTasks.lastWords.contains(key), let newest = best(all) { return newest }
        let named = all.filter { CodeTasks.fold($0.label) == key }
        if let task = best(named) { return task }
        let words = key.split(separator: " ")
        let partly = all.filter { job in
            let label = CodeTasks.fold(job.label)
            return !words.isEmpty && words.allSatisfy { label.split(separator: " ").contains($0) }
        }
        if let task = best(partly) { return task }
        let names = all.prefix(5).map { "\($0.label) (\($0.id))" }.joined(separator: ", ")
        throw ToolFailure(all.isEmpty ? "no tasks on this Mac yet" : "no such task on this Mac; its tasks: \(names)")
    }

    private func update(_ id: String, _ change: (inout Job) -> Void) {
        lock.locked {
            if var task = tasks[id] {
                change(&task)
                tasks[id] = task
            }
        }
    }

    /// A new run of the task's agent, counted (with `change`) before the call returns: a run
    /// it replaces, still ending, then knows at once that it is no longer current, however
    /// late the new run's own work gets going.
    private func nextRun(_ id: String, _ change: (inout Job) -> Void = { _ in }) -> Int {
        lock.locked {
            guard var task = tasks[id] else { return 0 }
            change(&task)
            task.runs += 1
            tasks[id] = task
            return task.runs
        }
    }

    // MARK: The tools

    public func start(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["repo", "instruction", "openInVSCode", "agent", "chat", "label"])
        let settings = try current()
        let name = try args.required("repo", limit: 60, what: "which repository")
        guard let repo = settings.repos[name] else {
            throw ToolFailure("that repository is not allowed here; allowed: \(settings.repos.keys.sorted().joined(separator: ", "))")
        }
        guard let agent = settings.agent(try args.text("agent", limit: 60)) else {
            throw ToolFailure("no agent by that name on this Mac; agents: \(settings.agentNames.joined(separator: ", "))")
        }
        let chat = try args.bool("chat") ?? false
        if chat && !agent.streamsInput {
            throw ToolFailure("the agent \(agent.name) cannot hold a conversation (it needs \"--input-format\", \"stream-json\" in tasks.json)")
        }
        // A chat may start with nothing to do yet ("hello").
        let given = chat ? try args.text("instruction", limit: 100_000) : try args.required("instruction", limit: 100_000, what: "what the task is")
        let instruction = (given ?? "").split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard instruction.count <= CodeTasks.maxInstruction else {
            throw ToolFailure("keep the task under \(CodeTasks.maxInstruction) characters")
        }
        let running = lock.locked { tasks.values.filter { CodeTasks.live.contains($0.status) }.count }
        guard running < CodeTasks.maxRunning else {
            throw ToolFailure("\(CodeTasks.maxRunning) tasks are running already; wait or stop one")
        }
        let id = "t" + String(UUID().uuidString.lowercased().prefix(6))
        let branch = PushGuard.taskPrefix + id
        let worktree = settings.worktrees.appendingPathComponent("\(repo.name)-\(id)")
        let base = try await git(repo.path, ["rev-parse", "HEAD"])
        try FileManager.default.createDirectory(at: settings.worktrees, withIntermediateDirectories: true)
        _ = try await git(repo.path, ["worktree", "add", "-b", branch, worktree.path, base])
        var task = Job(id: id, repo: repo, instruction: instruction, branch: branch, worktree: worktree, base: base, started: Date())
        task.agent = agent.name
        task.chat = chat
        let named = try args.text("label", limit: 60) ?? "\(repo.name) · \(agent.name)"
        task.label = lock.locked {
            // Unique among the tasks still going, so it can be said.
            let taken = Set(tasks.values.filter { $0.status != "stopped" }.map { CodeTasks.fold($0.label) })
            var label = named
            var number = 2
            while taken.contains(CodeTasks.fold(label)) {
                label = "\(named) \(number)"
                number += 1
            }
            return label
        }
        lock.locked { tasks[id] = task }
        let open = try args.bool("openInVSCode") ?? settings.openVSCode
        if open { await openVSCode(worktree) }
        let run = nextRun(id)
        Task { await self.run(id, run, settings: settings) }
        return [
            "id": .string(id), "repo": .string(repo.name), "branch": .string(branch), "worktree": .string(worktree.path),
            "agent": .string(agent.name), "label": .string(task.label), "chat": .bool(chat),
            "summary": .string(chat
                ? "\(task.label) is ready to chat (task \(id), on \(branch)\(open ? ", with VS Code open on it" : "")). Tell it things with code_task_say; its replies come back."
                : "Task \(id) (\(task.label)) started on \(branch)\(open ? ", with VS Code open on it" : ""). Ira says when it is done."),
        ]
    }

    public func status(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        var view = task.view()
        if case .object(var fields) = view {
            let latest = task.progress.last.map { " Latest: \($0)" } ?? ""
            let steps = task.done.flatMap { done in task.total.map { " \(done) of \($0) steps done." } } ?? ""
            let state = task.status == "waiting" ? "waiting for your next message" : task.status
            fields["summary"] = .string("\(task.label) (task \(task.id)) is \(state).\(steps)\(latest)")
            view = .object(fields)
        }
        return view
    }

    public func list(_ raw: JSONValue) async throws -> JSONValue {
        _ = try ToolArgs(raw, allowed: [])
        let settings = try current()
        let all = lock.locked { tasks.values.sorted { $0.started > $1.started } }
        return [
            "repos": .array(settings.repos.keys.sorted().map { .string($0) }),
            "agents": .array(settings.agentNames.map { .string($0) }), "defaultAgent": .string(settings.defaultAgent),
            "tasks": .array(all.map { ["id": .string($0.id), "label": .string($0.label), "chat": .bool($0.chat), "repo": .string($0.repo.name), "agent": .string($0.agent), "status": .string($0.status), "instruction": .string(String($0.instruction.prefix(200)))] }),
            "summary": .string(all.isEmpty ? "No tasks yet. Allowed repositories: \(settings.repos.keys.sorted().joined(separator: ", "))." : "\(all.count) task\(all.count == 1 ? "" : "s"): " + all.prefix(5).map { "\($0.label) (\($0.status))" }.joined(separator: ", ") + "."),
        ]
    }

    public func stop(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        if task.status == "paused" {
            update(task.id) { $0.status = "stopped" }
            return ["id": .string(task.id), "summary": .string("Stopped task \(task.id), which was paused. Its worktree and branch stay.")]
        }
        guard CodeTasks.live.contains(task.status) else {
            return ["id": .string(task.id), "summary": .string("Task \(task.id) had already \(task.status).")]
        }
        update(task.id) { $0.status = "stopped" }
        lock.locked { idlers.removeValue(forKey: task.id) }?.cancel()
        lock.locked { commands[task.id] }?.stop()
        return ["id": .string(task.id), "summary": .string("Stopped task \(task.id). Its worktree and branch stay.")]
    }

    /// One user turn on a stream-json agent's stdin.
    static func message(_ text: String) -> String {
        (["type": "user", "message": ["role": "user", "content": [["type": "text", "text": .string(text)]]]] as JSONValue).encoded() + "\n"
    }

    /// The person's words, cleaned and held to the task's own limit.
    func words(_ args: ToolArgs, _ name: String, required: Bool) throws -> String? {
        let raw = required ? try args.required(name, limit: 100_000, what: "what to tell it") : try args.text(name, limit: 100_000)
        guard let raw else { return nil }
        let text = raw.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard text.count <= CodeTasks.maxInstruction else { throw ToolFailure("keep it under \(CodeTasks.maxInstruction) characters") }
        return text
    }

    /// Tell a running task something ("write the tests first"), and hear its reply: it reads it
    /// after its current step, and its answer comes back within `replyWait`, or later as a
    /// task_reply event.
    public func say(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "text"])
        let task = try task(args)
        let text = try words(args, "text", required: true)!
        let agent = settings()?.agent(task.agent)
        guard CodeTasks.live.contains(task.status) else {
            throw ToolFailure("\(task.label) is \(task.status); to give it more to do, use code_task_resume with your words")
        }
        guard let agent, agent.streamsInput else {
            let other = agent?.resumes == true ? "pause it, then resume it with your words" : "stop it and start a new task"
            throw ToolFailure("this task's agent cannot be told anything while it works; \(other)")
        }
        try lock.locked {
            guard let command = commands[task.id], command.acceptsInput else {
                throw ToolFailure("it has just finished its work; when it is done, resume it with your words")
            }
            if var job = tasks[task.id] {
                job.awaiting = true
                job.early = nil
                tasks[task.id] = job
            }
            try command.write(CodeTasks.message(text))
            if var job = tasks[task.id] {
                job.sent += 1
                job.stepsSince = []
                if job.status == "waiting" { job.status = "running" }
                job.progress = Array((job.progress + ["you said: \(AgentOutput.short(text, 120))"]).suffix(5))
                tasks[task.id] = job
            }
            idlers.removeValue(forKey: task.id)?.cancel()
        }
        let reply = await nextReply(task.id, seconds: replyWait)
        let steps = lock.locked { tasks[task.id]?.stepsSince ?? [] }
        let told = "Told \(task.label) “\(AgentOutput.short(text, 120))”."
        var out: [String: JSONValue] = [
            "id": .string(task.id), "label": .string(task.label), "steps": .array(steps.map { .string($0) }),
        ]
        if let reply {
            out["reply"] = .string(reply)
            out["summary"] = .string("\(told) It says: \(reply)")
        } else {
            out["summary"] = .string(task.chat
                ? "\(told) It is still working on it; its reply comes to you as a message."
                : "\(told) It reads it after its current step; Ira says when the task is done.")
        }
        return .object(out)
    }

    /// The task's next reply within `seconds`, or nil: then a chat task's reply goes out as a
    /// task_reply event when it comes.
    private func nextReply(_ id: String, seconds: Double) async -> String? {
        let token = UUID()
        return await withCheckedContinuation { continuation in
            let (ready, replaced): (String?, CheckedContinuation<String?, Never>?) = lock.locked {
                if let early = tasks[id]?.early {
                    tasks[id]?.early = nil
                    tasks[id]?.awaiting = false
                    return (early, nil)
                }
                let replaced = waiters[id]?.reply
                waiters[id] = (token, continuation)
                return (nil, replaced)
            }
            replaced?.resume(returning: nil)
            if let ready {
                continuation.resume(returning: ready)
                return
            }
            Task {
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                let mine: CheckedContinuation<String?, Never>? = self.lock.locked {
                    guard self.waiters[id]?.token == token else { return nil }
                    self.tasks[id]?.awaiting = false
                    return self.waiters.removeValue(forKey: id)?.reply
                }
                mine?.resume(returning: nil)
            }
        }
    }

    /// A chat task with nothing said for `chatIdle`: paused when its agent can go on later,
    /// else stopped.
    private func idleOut(_ id: String) {
        guard let job = lock.locked({ tasks[id] }), job.status == "waiting" else { return }
        let resumes = settings()?.agent(job.agent)?.resumes == true && job.session != nil
        update(id) { $0.status = resumes ? "paused" : "stopped" }
        lock.locked { commands[id] }?.stop()
    }

    /// Pause a running task: its agent stops, and its session is kept for code_task_resume.
    public func pause(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        guard CodeTasks.live.contains(task.status) else {
            throw ToolFailure("\(task.label) is \(task.status), not running")
        }
        guard settings()?.agent(task.agent)?.resumes == true, task.session != nil else {
            throw ToolFailure("this task's agent cannot continue later, so a pause would lose its place; stop it instead (code_task_stop)")
        }
        update(task.id) { $0.status = "paused" }
        lock.locked { idlers.removeValue(forKey: task.id) }?.cancel()
        lock.locked { commands[task.id] }?.stop()
        return ["id": .string(task.id), "summary": .string("Paused \(task.label). Resume it with code_task_resume, with words for it if you like.")]
    }

    /// Continue a paused (or finished) task in its worktree, from where its agent left off.
    public func resume(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "text"])
        let task = try task(args)
        let text = try words(args, "text", required: false)
        let settings = try current()
        guard ["paused", "done", "failed", "stopped"].contains(task.status) else {
            throw ToolFailure("task \(task.id) is \(task.status); tell a running task something with code_task_say")
        }
        guard let agent = settings.agent(task.agent), agent.resumes else {
            throw ToolFailure("this task's agent is not set up to continue a session (\"resume\" in tasks.json); start a new task")
        }
        guard let session = task.session else {
            throw ToolFailure("its agent never said its session id, so it cannot continue; start a new task")
        }
        let running = lock.locked { tasks.values.filter { CodeTasks.live.contains($0.status) }.count }
        guard running < CodeTasks.maxRunning else {
            throw ToolFailure("\(CodeTasks.maxRunning) tasks are running already; wait or stop one")
        }
        let run = nextRun(task.id) {
            $0.status = "starting"
            $0.error = ""
            $0.result = ""
            $0.finished = nil
            if let text { $0.progress = Array(($0.progress + ["you said: \(AgentOutput.short(text, 120))"]).suffix(5)) }
        }
        Task { await self.run(task.id, run, settings: settings, words: text ?? "Continue where you left off.", session: session) }
        return ["id": .string(task.id), "summary": .string("Task \(task.id) goes on in \(task.repo.name) with \(agent.name). Ira says when it is done.")]
    }

    public func push(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        guard task.status == "done" else { throw ToolFailure("task \(task.id) is \(task.status); only a finished task is pushed") }
        let head = try await git(task.worktree, ["rev-parse", "--abbrev-ref", "HEAD"])
        guard head == task.branch else { throw ToolFailure("the worktree is on \(head), not the task's branch \(task.branch)") }
        let remoteHead = try? await git(task.repo.path, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        let defaultBranch = remoteHead.map { $0.hasPrefix("origin/") ? String($0.dropFirst("origin/".count)) : $0 }
        if let refusal = PushGuard.refusal(branch: task.branch, defaultBranch: defaultBranch, protected: task.repo.protected) {
            throw ToolFailure(refusal)
        }
        // As the person, outside the sandbox and without the task's no-push settings.
        _ = try await git(task.worktree, PushGuard.pushArguments(branch: task.branch), timeout: 120)
        return ["id": .string(task.id), "summary": .string("Pushed \(task.branch) to origin. Nothing was merged.")]
    }

    // MARK: Running

    /// Whether another step done should be said now: the first at once, then at most one a
    /// `spacing`, and the last step always.
    public static func stepDue(done: Int, total: Int, last: Date?, now: Date, spacing: Double) -> Bool {
        guard let last else { return true }
        return done >= total || now.timeIntervalSince(last) >= spacing
    }

    /// Whether a running task should say how it is going now.
    public static func progressDue(started: Date, last: Date, now: Date) -> Bool {
        let running = now.timeIntervalSince(started)
        guard running >= progressAfter else { return false }
        return last == started || now.timeIntervalSince(last) >= progressEvery
    }

    func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"] = "core.hooksPath"
        env["GIT_CONFIG_VALUE_0"] = hooks.path
        env["GIT_CONFIG_KEY_1"] = "remote.origin.pushurl"
        env["GIT_CONFIG_VALUE_1"] = CodeTasks.noPushURL
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env
    }

    /// argv inside macOS's sandbox, when it is on and this Mac has it.
    func sandboxed(_ argv: [String], task: Job, settings: TaskSettings) -> [String] {
        guard settings.sandbox, FileManager.default.isExecutableFile(atPath: CodeTasks.sandboxExec) else { return argv }
        let extra = settings.writable.indices
            .map { "  (subpath (param \"W\($0)\")) (literal (param \"W\($0)\"))" }.joined(separator: "\n")
        var params = [
            "-D", "HOME=\(FileManager.default.homeDirectoryForCurrentUser.path)",
            "-D", "WORKTREE=\(task.worktree.resolvingSymlinksInPath().path)",
            "-D", "GITDIR=\(task.repo.path.appendingPathComponent(".git").resolvingSymlinksInPath().path)",
        ]
        for (index, path) in settings.writable.enumerated() {
            params += ["-D", "W\(index)=\(path.resolvingSymlinksInPath().path)"]
        }
        return [CodeTasks.sandboxExec, "-p", CodeTasks.profile.replacingOccurrences(of: "{extra}", with: extra)] + params + argv
    }

    static func argv(_ command: [String], prompt: String) -> [String] {
        if command.contains(where: { $0.contains("{prompt}") }) {
            return command.map { $0.replacingOccurrences(of: "{prompt}", with: prompt) }
        }
        return command + [prompt]
    }

    /// The agent's command line: the task in it (or, for a stream-json agent, on its stdin),
    /// and what continues `session` when there is one.
    static func argv(_ agent: TaskSettings.Agent, prompt: String, session: String?) -> [String] {
        var argv = agent.streamsInput ? agent.command.filter { !$0.contains("{prompt}") } : argv(agent.command, prompt: prompt)
        if let session, let resume = agent.resume {
            argv += resume.map { $0.replacingOccurrences(of: "{session}", with: session) }
        }
        return argv
    }

    /// Run the task's agent: from the start, or with `words` continuing `session`. `run` is the
    /// number nextRun gave it.
    private func run(_ id: String, _ run: Int, settings: TaskSettings, words: String? = nil, session: String? = nil) async {
        guard let task = lock.locked({ tasks[id] }) else { return }
        guard let agent = settings.agent(task.agent) else {
            update(id) { $0.error = "the agent \($0.agent) is no longer set up on this Mac" }
            await finish(id)
            return
        }
        let instruction = task.chat && task.instruction.isEmpty ? CodeTasks.chatOpening : task.instruction
        let prompt = session != nil ? (words ?? "") : CodeTasks.prompt.replacingOccurrences(of: "{repo}", with: task.repo.name)
            .replacingOccurrences(of: "{branch}", with: task.branch)
            .replacingOccurrences(of: "{instruction}", with: instruction)
        do {
            let command = try Command.start(
                sandboxed(CodeTasks.argv(agent, prompt: prompt, session: session), task: task, settings: settings),
                directory: task.worktree.path, environment: environment(), keepInput: agent.streamsInput)
            try lock.locked {
                commands[id] = command
                if agent.streamsInput {
                    try command.write(CodeTasks.message(prompt))
                    tasks[id]?.sent = 1
                    tasks[id]?.answered = 0
                }
            }
            update(id) { if $0.status == "starting" { $0.status = "running" } }
            // A chat lasts as long as the person talks to it: it pauses when idle instead.
            let timer: Task<Void, Error>? = task.chat ? nil : Task {
                try await Task.sleep(nanoseconds: UInt64(settings.minutes * 60 * 1_000_000_000))
                self.update(id) { $0.error = "it took longer than \(Int(settings.minutes)) minutes" }
                command.stop()
            }
            async let errors = Command.readAll(command.stderr, limit: 16 * 1024)
            var final: JSONValue?
            var lastProgressEvent = task.started
            var steps = StepTracker()
            var lastStepEvent: Date?
            for await line in Command.lines(command.stdout) {
                // The latest: a resumed agent may go on under a new session id.
                if let session = AgentOutput.session(line) { update(id) { $0.session = session } }
                let advanced = steps.feed(line)
                if steps.counting {
                    update(id) {
                        $0.done = steps.done
                        $0.total = steps.total
                        $0.current = steps.current
                    }
                }
                let now = Date()
                if advanced, CodeTasks.stepDue(done: steps.done, total: steps.total, last: lastStepEvent, now: now, spacing: stepSpacing) {
                    lastStepEvent = now
                    announce("task_progress", "Task \(task.id) in \(task.repo.name): \(steps.done) of \(steps.total) done",
                             steps.sentence, ["id": .string(task.id), "repo": .string(task.repo.name)])
                }
                let done = AgentOutput.steps(line)
                if !done.isEmpty { update(id) { $0.stepsSince = Array(($0.stepsSince + done).suffix(10)) } }
                let (progress, result) = AgentOutput.progress(line)
                if let progress {
                    update(id) { $0.progress = Array(($0.progress + [progress]).suffix(5)) }
                    // Agents without a task list say how it is going by the clock.
                    if !steps.counting, CodeTasks.progressDue(started: task.started, last: lastProgressEvent, now: now) {
                        lastProgressEvent = now
                        let minutes = Int(now.timeIntervalSince(task.started) / 60)
                        announce("task_progress", "Task \(task.id) in \(task.repo.name): \(minutes) minutes in",
                                 progress, ["id": .string(task.id), "repo": .string(task.repo.name)])
                    }
                }
                if let result {
                    final = result
                    let reply = AgentOutput.short(SecretFilter.mask(result["result"]?.stringValue ?? ""), CodeTasks.maxReply)
                    // To code_task_say waiting for it, else kept for it, else (a chat's) as an event.
                    let (waiter, announced, job): (CheckedContinuation<String?, Never>?, Bool, Job?) = lock.locked {
                        tasks[id]?.answered += 1
                        let waiter = waiters.removeValue(forKey: id)?.reply
                        var announced = false
                        if waiter != nil {
                            tasks[id]?.awaiting = false
                        } else if tasks[id]?.awaiting == true {
                            tasks[id]?.early = reply
                        } else {
                            announced = tasks[id]?.chat == true
                        }
                        if let job = tasks[id] {
                            if job.chat {
                                if job.status == "running" || job.status == "starting" { tasks[id]?.status = "waiting" }
                            } else if job.answered >= job.sent {
                                // Every message answered: close its input, so it finishes.
                                command.closeInput()
                            }
                        }
                        return (waiter, announced, tasks[id])
                    }
                    waiter?.resume(returning: reply)
                    if announced, let job {
                        announce("task_reply", "\(job.label) says", reply.isEmpty ? "(no words)" : reply,
                                 ["id": .string(job.id), "label": .string(job.label), "repo": .string(job.repo.name)])
                    }
                    if job?.chat == true {
                        let idle = Task { [weak self, chatIdle] in
                            try? await Task.sleep(nanoseconds: UInt64(chatIdle * 1_000_000_000))
                            guard !Task.isCancelled else { return }
                            self?.idleOut(id)
                        }
                        lock.locked { idlers.updateValue(idle, forKey: id) }?.cancel()
                    }
                }
            }
            let code = await command.wait()
            timer?.cancel()
            lock.locked { idlers.removeValue(forKey: id) }?.cancel()
            let stderr = await errors
            let (current, paused): (Bool, Bool) = lock.locked {
                let current = tasks[id]?.runs == run
                if current, commands[id] === command, tasks[id]?.status == "paused" { commands[id] = nil }
                return (current, tasks[id]?.status == "paused")
            }
            // Paused (its session is kept for code_task_resume), or already resumed by another run.
            if !current || paused { return }
            update(id) { task in
                if task.status == "stopped" {
                    task.error = task.error.isEmpty ? "stopped" : task.error
                } else if let final {
                    task.result = final["result"]?.stringValue ?? ""
                    if final["is_error"]?.boolValue == true {
                        task.error = AgentOutput.short(task.result.isEmpty ? "the agent reported an error" : task.result)
                    }
                } else if task.result.isEmpty {
                    task.result = task.progress.joined(separator: " ")
                }
                if code != 0 && task.error.isEmpty && task.status != "stopped" {
                    let tail = stderr.split(separator: "\n").suffix(3).joined(separator: " ")
                    task.error = AgentOutput.short(tail.isEmpty ? "the agent exited with code \(code)" : tail)
                }
            }
        } catch {
            update(id) { $0.error = AgentOutput.short((error as? ToolFailure)?.message ?? "\(error)") }
        }
        let current: Bool = lock.locked {
            guard tasks[id]?.runs == run else { return false }
            commands[id] = nil
            return true
        }
        if current { await finish(id) }
    }

    private func finish(_ id: String) async {
        guard let task = lock.locked({ tasks[id] }) else { return }
        let files = (try? await changed(task)) ?? []
        var tests = task.tests
        if task.error.isEmpty, let test = task.repo.test, let settings = settings() {
            tests = await runTests(test, task: task, settings: settings)
        }
        update(id) { task in
            task.files = files
            task.tests = tests
            if task.status != "stopped" { task.status = task.error.isEmpty ? "done" : "failed" }
            task.finished = Date()
        }
        guard let done = lock.locked({ tasks[id] }) else { return }
        let changedText = "\(done.files.count) file\(done.files.count == 1 ? "" : "s") changed"
        let data: JSONValue = [
            "id": .string(done.id), "repo": .string(done.repo.name), "branch": .string(done.branch),
            "files": .array(done.files.map { .string($0) }), "tests": .string(done.tests),
        ]
        if done.status == "done" {
            let summary = AgentOutput.short(done.result, 400)
            announce("task_done", "Task \(done.id) in \(done.repo.name) is done",
                     "\(summary.isEmpty ? "No summary." : summary) \(changedText). Tests: \(done.tests).", data)
        } else {
            announce("task_failed", "Task \(done.id) in \(done.repo.name) \(done.status)",
                     "\(done.error.isEmpty ? done.status : done.error). \(changedText).", data)
        }
    }

    func changed(_ task: Job) async throws -> [String] {
        let lists = [
            try await git(task.worktree, ["diff", "--name-only", "\(task.base)..HEAD"]),
            try await git(task.worktree, ["diff", "--name-only", "HEAD"]),
            try await git(task.worktree, ["ls-files", "--others", "--exclude-standard"]),
        ]
        var seen: [String] = []
        for line in lists.flatMap({ $0.split(separator: "\n").map(String.init) }) where !line.isEmpty && !seen.contains(line) {
            seen.append(line)
        }
        return Array(seen.prefix(CodeTasks.maxFiles))
    }

    func runTests(_ test: String, task: Job, settings: TaskSettings) async -> String {
        do {
            let result = try await Command.run(
                sandboxed(["/bin/sh", "-c", test], task: task, settings: settings), directory: task.worktree.path,
                environment: environment(), timeout: 15 * 60)
            if result.timedOut { return "stopped after 15 minutes" }
            if result.status == 0 { return "passed" }
            let tail = (result.stdout + "\n" + result.stderr).split(separator: "\n").suffix(3).joined(separator: " ")
            return AgentOutput.short("failed (exit \(result.status)): \(tail)", 300)
        } catch {
            return "could not run"
        }
    }

    /// git as the person: not sandboxed (the agent never runs this).
    func git(_ folder: URL, _ args: [String], timeout: Double = 120) async throws -> String {
        var env = ProcessInfo.processInfo.environment
        env["GIT_TERMINAL_PROMPT"] = "0"
        let result = try await Command.run(["/usr/bin/git", "-C", folder.path] + args, environment: env, timeout: timeout)
        if result.timedOut { throw ToolFailure("git \(args.first ?? "") took too long") }
        guard result.status == 0 else {
            if result.stderr.contains("Operation not permitted") {
                throw ToolFailure("macOS keeps Ira out of \(folder.path). Allow Ira in System Settings → Privacy & Security → Files and Folders (Documents), then ask again")
            }
            throw ToolFailure(AgentOutput.short("git \(args.first ?? ""): \(result.stderr)", 300))
        }
        return result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
