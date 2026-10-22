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
///   "command": ["/path/to/agent", "-p", "{prompt}", "--output-format", "stream-json"],
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

    public var command: [String]
    public var repos: [String: Repo]
    public var worktrees: URL
    public var writable: [URL]
    public var minutes: Double
    public var sandbox: Bool
    public var openVSCode: Bool
    public var promptURI: String?

    public static var defaultPath: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Ira/tasks.json")
    }

    static func expand(_ path: String, home: URL) -> URL {
        PathPolicy.expand(path, home: home) ?? URL(fileURLWithPath: path)
    }

    /// The settings in a tasks.json; nil when tasks are not set up on this Mac.
    public static func parse(_ data: Data, home: URL = FileManager.default.homeDirectoryForCurrentUser) -> TaskSettings? {
        guard let raw = JSONValue.parse(data), raw.objectValue != nil else { return nil }
        let command = (raw["command"]?.arrayValue ?? []).compactMap(\.stringValue)
        var repos: [String: Repo] = [:]
        for (name, entry) in raw["repos"]?.objectValue ?? [:] {
            let path = entry.stringValue ?? entry["path"]?.stringValue
            guard let path, !path.isEmpty, name.range(of: #"^[A-Za-z0-9._-]{1,60}$"#, options: .regularExpression) != nil else { continue }
            repos[name] = Repo(
                name: name, path: expand(path, home: home), test: entry["test"]?.stringValue,
                protected: entry["protected"]?.boolValue ?? false)
        }
        guard !command.isEmpty, !repos.isEmpty else { return nil }
        let vscode = raw["vscode"]
        return TaskSettings(
            command: command, repos: repos,
            worktrees: expand(raw["worktrees"]?.stringValue ?? "~/ira-tasks", home: home),
            writable: (raw["writable"]?.arrayValue ?? []).compactMap(\.stringValue).map { expand($0, home: home) },
            minutes: raw["minutes"]?.doubleValue ?? 60,
            sandbox: raw["sandbox"]?.boolValue ?? true,
            openVSCode: vscode?["open"]?.boolValue ?? true,
            promptURI: vscode?["promptURI"]?.stringValue)
    }

    public static func load(from url: URL = defaultPath) -> TaskSettings? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return parse(data)
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

    /// (a progress line, the final result) from one line.
    public static func progress(_ line: String) -> (String?, JSONValue?) {
        let line = line.trimmingCharacters(in: .whitespaces)
        guard !line.isEmpty else { return (nil, nil) }
        guard let item = JSONValue.parse(line) else { return (short(line), nil) }
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
    public static let maxInstruction = 4000
    public static let maxFiles = 50
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
        public var status = "starting"  // starting, running, done, failed, stopped
        public var finished: Date?
        public var progress: [String] = []
        public var result = ""
        public var error = ""
        public var files: [String] = []
        public var tests = "not run"

        func view() -> JSONValue {
            [
                "id": .string(id), "repo": .string(repo.name), "branch": .string(branch), "status": .string(status),
                "instruction": .string(String(instruction.prefix(200))), "worktree": .string(worktree.path),
                "progress": .array(progress.map { .string($0) }), "summary": .string(String(result.prefix(2000))),
                "error": .string(error), "files": .array(files.map { .string($0) }), "tests": .string(tests),
            ]
        }
    }

    private let settings: @Sendable () -> TaskSettings?
    public var announce: Announce
    private let openVSCode: @Sendable (URL) async -> Void
    private let lock = NSLock()
    private var tasks: [String: Job] = [:]
    private var commands: [String: Command] = [:]
    private let hooks: URL

    public init(
        settings: @escaping @Sendable () -> TaskSettings? = { TaskSettings.load() },
        openVSCode: @escaping @Sendable (URL) async -> Void = { try? await AppTools.openInVSCode($0) },
        announce: @escaping Announce = { _, _, _, _ in }
    ) {
        self.settings = settings
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

    private func current() throws -> TaskSettings {
        guard let settings = settings() else {
            throw ToolFailure("coding tasks are not set up on this Mac (see Ira for Mac's guide: tasks.json)")
        }
        return settings
    }

    private func task(_ args: ToolArgs) throws -> Job {
        let id = try args.required("id", limit: 40, what: "which task (its id)")
        guard let task = lock.locked({ tasks[id] }) else { throw ToolFailure("no such task on this Mac") }
        return task
    }

    private func update(_ id: String, _ change: (inout Job) -> Void) {
        lock.locked {
            if var task = tasks[id] {
                change(&task)
                tasks[id] = task
            }
        }
    }

    // MARK: The tools

    public func start(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["repo", "instruction", "openInVSCode"])
        let settings = try current()
        let name = try args.required("repo", limit: 60, what: "which repository")
        guard let repo = settings.repos[name] else {
            throw ToolFailure("that repository is not allowed here; allowed: \(settings.repos.keys.sorted().joined(separator: ", "))")
        }
        let instruction = (try args.required("instruction", limit: 100_000, what: "what the task is"))
            .split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard instruction.count <= CodeTasks.maxInstruction else {
            throw ToolFailure("keep the task under \(CodeTasks.maxInstruction) characters")
        }
        let running = lock.locked { tasks.values.filter { ["starting", "running"].contains($0.status) }.count }
        guard running < CodeTasks.maxRunning else {
            throw ToolFailure("\(CodeTasks.maxRunning) tasks are running already; wait or stop one")
        }
        let id = "t" + String(UUID().uuidString.lowercased().prefix(6))
        let branch = PushGuard.taskPrefix + id
        let worktree = settings.worktrees.appendingPathComponent("\(repo.name)-\(id)")
        let base = try await git(repo.path, ["rev-parse", "HEAD"])
        try FileManager.default.createDirectory(at: settings.worktrees, withIntermediateDirectories: true)
        _ = try await git(repo.path, ["worktree", "add", "-b", branch, worktree.path, base])
        let task = Job(id: id, repo: repo, instruction: instruction, branch: branch, worktree: worktree, base: base, started: Date())
        lock.locked { tasks[id] = task }
        let open = try args.bool("openInVSCode") ?? settings.openVSCode
        if open { await openVSCode(worktree) }
        Task { await self.run(id, settings: settings) }
        return [
            "id": .string(id), "repo": .string(repo.name), "branch": .string(branch), "worktree": .string(worktree.path),
            "summary": .string("Task \(id) started in \(repo.name) on \(branch)\(open ? ", with VS Code open on it" : ""). Ira says when it is done."),
        ]
    }

    public func status(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        var view = task.view()
        if case .object(var fields) = view {
            let latest = task.progress.last.map { " Latest: \($0)" } ?? ""
            fields["summary"] = .string("Task \(task.id) in \(task.repo.name) is \(task.status).\(latest)")
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
            "tasks": .array(all.map { ["id": .string($0.id), "repo": .string($0.repo.name), "status": .string($0.status), "instruction": .string(String($0.instruction.prefix(200)))] }),
            "summary": .string(all.isEmpty ? "No tasks yet. Allowed repositories: \(settings.repos.keys.sorted().joined(separator: ", "))." : "\(all.count) task\(all.count == 1 ? "" : "s"); \(all.filter { $0.status == "running" }.count) running."),
        ]
    }

    public func stop(_ raw: JSONValue) async throws -> JSONValue {
        let task = try task(try ToolArgs(raw, allowed: ["id"]))
        guard ["starting", "running"].contains(task.status) else {
            return ["id": .string(task.id), "summary": .string("Task \(task.id) had already \(task.status).")]
        }
        update(task.id) { $0.status = "stopped" }
        lock.locked { commands[task.id] }?.stop()
        return ["id": .string(task.id), "summary": .string("Stopped task \(task.id). Its worktree and branch stay.")]
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

    private func run(_ id: String, settings: TaskSettings) async {
        guard let task = lock.locked({ tasks[id] }) else { return }
        let prompt = CodeTasks.prompt.replacingOccurrences(of: "{repo}", with: task.repo.name)
            .replacingOccurrences(of: "{branch}", with: task.branch)
            .replacingOccurrences(of: "{instruction}", with: task.instruction)
        do {
            let command = try Command.start(
                sandboxed(CodeTasks.argv(settings.command, prompt: prompt), task: task, settings: settings),
                directory: task.worktree.path, environment: environment())
            lock.locked { commands[id] = command }
            update(id) { if $0.status == "starting" { $0.status = "running" } }
            let timer = Task {
                try await Task.sleep(nanoseconds: UInt64(settings.minutes * 60 * 1_000_000_000))
                self.update(id) { $0.error = "it took longer than \(Int(settings.minutes)) minutes" }
                command.stop()
            }
            async let errors = Command.readAll(command.stderr, limit: 16 * 1024)
            var final: JSONValue?
            var lastProgressEvent = task.started
            for await line in Command.lines(command.stdout) {
                let (progress, result) = AgentOutput.progress(line)
                if let progress {
                    update(id) { $0.progress = Array(($0.progress + [progress]).suffix(5)) }
                    let now = Date()
                    if CodeTasks.progressDue(started: task.started, last: lastProgressEvent, now: now) {
                        lastProgressEvent = now
                        let minutes = Int(now.timeIntervalSince(task.started) / 60)
                        announce("task_progress", "Task \(task.id) in \(task.repo.name): \(minutes) minutes in",
                                 progress, ["id": .string(task.id), "repo": .string(task.repo.name)])
                    }
                }
                if let result { final = result }
            }
            let code = await command.wait()
            timer.cancel()
            let stderr = await errors
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
        lock.locked { commands[id] = nil }
        await finish(id)
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
