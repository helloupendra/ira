import AppKit
import Foundation
import Testing
@testable import IraKit

@Suite("The whole toolset")
struct CatalogTests {
    static let everything = ToolCatalog.all(tasksConfigured: true)

    @Test func fitsTheServersLimits() throws {
        let names = CatalogTests.everything.compactMap { $0["name"]?.stringValue }
        #expect(names.count == CatalogTests.everything.count)
        #expect(names.count <= 30)
        #expect(Set(names).count == names.count)
        #expect(ToolCatalog.all(tasksConfigured: false).count == names.count - ToolCatalog.tasks.count)
        let hello = DeviceProtocol.hello(label: "Studio Mac", tools: CatalogTests.everything).encoded()
        #expect(hello.utf8.count < 64 * 1024)
        for tool in CatalogTests.everything {
            let name = try #require(tool["name"]?.stringValue)
            #expect(name.range(of: #"^[a-z][a-z0-9_]{2,40}$"#, options: .regularExpression) != nil, "\(name)")
            let description = try #require(tool["description"]?.stringValue)
            #expect((30...1000).contains(description.count), "\(name)")
            let parameters = try #require(tool["parameters"])
            #expect(parameters["type"] == "object")
            #expect(parameters["additionalProperties"] == false)
            #expect(parameters.encoded().utf8.count < 8 * 1024, "\(name)")
            let properties = try #require(parameters["properties"]?.objectValue)
            for required in parameters["required"]?.arrayValue ?? [] {
                #expect(properties[required.stringValue ?? ""] != nil, "\(name): \(required)")
            }
            for (key, schema) in properties {
                #expect(schema["type"]?.stringValue != nil, "\(name).\(key)")
                #expect(schema["description"]?.stringValue != nil, "\(name).\(key)")
            }
        }
    }

    /// Skills use the server's names; tiers follow the rules: read 0, open or add 1,
    /// reach someone or change the calendar 2, push 3.
    @Test func skillsAndTiers() {
        var table: [String: String] = [:]
        for tool in CatalogTests.everything {
            table[tool["name"]!.stringValue!] = "\(tool["skill"]!.stringValue!) \(tool["tier"]!.intValue!)"
        }
        #expect(table == [
            "files_find": "files 0", "file_read": "files 0", "file_open": "files 1", "screen_read": "screen 0",
            "browser_tabs": "browser 0", "browser_show_tab": "browser 1",
            "contacts_lookup": "contacts 0",
            "calendar_read": "calendar 0", "calendar_add": "calendar 2",
            "reminders_list": "reminders 0", "reminders_add": "reminders 1", "reminders_done": "reminders 1",
            "mail_search": "mail 0", "mail_read": "mail 0", "mail_draft": "mail 2",
            "messages_send": "messages 2",
            "notes_search": "notes 0", "notes_read": "notes 0", "notes_add": "notes 1",
            "app_open": "apps 1", "url_open": "apps 2", "vscode_open": "apps 1",
            "clipboard_read": "clipboard 0",
            "shortcuts_list": "shortcuts 0", "shortcuts_run": "shortcuts 2",
            "code_task_start": "tasks 2", "code_task_status": "tasks 0", "code_task_list": "tasks 0",
            "code_task_stop": "tasks 1", "code_task_push": "tasks 3",
        ])
    }

    @Test func everyToolHasAVerbForWhatIRead() {
        for tool in CatalogTests.everything {
            let name = tool["name"]!.stringValue!
            #expect(Activity(tool: name, target: "", ok: true).verb != name, "\(name)")
        }
    }

    @Test func whatIReadNeverHoldsAMessage() {
        let target = Toolbox.target("messages_send", ["to": "+919876543210", "name": "Avery Example", "text": "the secret plan"])
        #expect(target == "to Avery Example")
        let draft = Toolbox.target("mail_draft", ["to": ["avery@example.com"], "subject": "x", "body": "private words"])
        #expect(draft == "to avery@example.com")
        #expect(Toolbox.target("url_open", ["url": "https://example.com/a?token=abc"]) == "example.com")
    }
}

@Suite("Arguments and dates")
struct ArgsTests {
    @Test func argumentsAreChecked() throws {
        #expect(throws: ToolFailure("unknown argument(s): x")) { try ToolArgs(["x": 1], allowed: ["y"]) }
        let args = try ToolArgs(["to": "a@example.com, b@example.com", "n": 99, "flag": true, "empty": "  "], allowed: ["to", "n", "flag", "empty"])
        #expect(try args.list("to") == ["a@example.com", "b@example.com"])
        #expect(try args.number("n", 1...10) == 10)
        #expect(try args.bool("flag") == true)
        #expect(try args.text("empty") == nil)
        #expect(throws: ToolFailure("say the title")) { try args.required("title") }
    }

    @Test func dates() throws {
        let tz = TimeZone(identifier: "Asia/Kolkata")!
        let day = try #require(LocalDate.parse("2026-10-23", timeZone: tz))
        #expect(!day.hasTime)
        #expect(LocalDate.iso(day.date, timeZone: tz) == "2026-10-23T00:00:00+05:30")
        let time = try #require(LocalDate.parse("2026-10-23T14:30", timeZone: tz))
        #expect(time.hasTime)
        #expect(LocalDate.iso(time.date, timeZone: tz) == "2026-10-23T14:30:00+05:30")
        #expect(LocalDate.parse("2026-10-23 9:05:10", timeZone: tz).map { LocalDate.iso($0.date, timeZone: tz) } == "2026-10-23T09:05:10+05:30")
        #expect(LocalDate.parse("2026-10-23T09:00:00Z", timeZone: tz).map { LocalDate.iso($0.date, timeZone: tz) } == "2026-10-23T14:30:00+05:30")
        #expect(LocalDate.parse("2026-10-23T09:00+0100", timeZone: tz).map { LocalDate.iso($0.date, timeZone: tz) } == "2026-10-23T13:30:00+05:30")
        for bad in ["tomorrow", "2026-02-30", "2026-13-01", "2026-10-23T25:00", ""] {
            #expect(LocalDate.parse(bad, timeZone: tz) == nil, "\(bad)")
        }
        #expect(LocalDate.spoken(time.date, timeZone: tz) == "Fri 23 Oct, 14:30")
    }
}

@Suite("Contacts, mail, notes and messages")
struct PersonalToolTests {
    @Test func whatAQueryIs() {
        #expect(ContactsTool.kind(of: "+91 98765 43210") == .number("919876543210"))
        #expect(ContactsTool.kind(of: "Avery@Example.com") == .email("avery@example.com"))
        #expect(ContactsTool.kind(of: "Avery Example") == .name("Avery Example"))
        #expect(ContactsTool.kind(of: "Avery 2") == .name("Avery 2"))
    }

    @Test func numbersMatchHoweverTheyAreWritten() {
        #expect(ContactsTool.sameNumber("9876543210", "+91 98765 43210"))
        #expect(ContactsTool.sameNumber("+91-98765-43210", "098765 43210"))
        #expect(ContactsTool.sameNumber("43210", "+91 98765 43210"))
        #expect(!ContactsTool.sameNumber("9876543211", "+91 98765 43210"))
        #expect(!ContactsTool.sameNumber("12", "+91 98765 43210"))
    }

    @Test func scriptOutput() {
        let output = "1\u{1F}INBOX\u{1F}Work\u{1F}Invoice 42\u{1F}Avery <avery@example.com>\u{1F}2026-10-22T10:00:00\u{1F}false\u{1E}\n"
        #expect(AppleScriptTools.records(output) == [["1", "INBOX", "Work", "Invoice 42", "Avery <avery@example.com>", "2026-10-22T10:00:00", "false"]])
        #expect(AppleScriptTools.records("") == [])
        let id = AppleScriptTools.mailID(account: "Work", mailbox: "Clients/2026", id: "812")
        #expect(AppleScriptTools.parseMailID(id)! == ("Work", "Clients/2026", "812"))
        #expect(AppleScriptTools.parseMailID("not an id") == nil)
    }

    @Test func permissionFailuresSayWhatToDo() {
        #expect(AppleScriptTools.failure("Mail", "execution error: Not authorized to send Apple events to Mail. (-1743)").message
            .contains("Privacy & Security → Automation"))
        #expect(AppleScriptTools.failure("Notes", "Can’t get note id \"x\". (-1728)").message == "Notes has nothing that matches")
    }

    @Test func addresses() {
        #expect(AppleScriptTools.isEmail("avery@example.com"))
        #expect(!AppleScriptTools.isEmail("Avery Example"))
        #expect(AppleScriptTools.messageHandle("+91 98765-43210") == "+919876543210")
        #expect(AppleScriptTools.messageHandle("avery@example.com") == "avery@example.com")
        #expect(AppleScriptTools.messageHandle("Avery") == nil)
        #expect(AppleScriptTools.messageHandle("123") == nil)
        #expect(AppleScriptTools.messageHandle("98765; do shell script") == nil)
    }

    @Test func noteBodiesAreEscaped() {
        #expect(AppleScriptTools.noteHTML(title: "Plan <b>", body: "a & b\n\nc")
            == "<div><b>Plan &lt;b&gt;</b></div><div>a &amp; b</div><div><br></div><div>c</div>")
    }

    /// The fixed scripts are valid AppleScript (compiling launches no app).
    @Test(arguments: [
        AppleScriptTools.mailSearch, AppleScriptTools.mailRead, AppleScriptTools.mailDraft,
        AppleScriptTools.notesSearch, AppleScriptTools.notesRead, AppleScriptTools.notesAdd,
        AppleScriptTools.messagesSend,
    ])
    func scriptsCompile(script: String) async throws {
        let folder = try temporaryFolder()
        let source = folder.appendingPathComponent("tool.applescript")
        try script.write(to: source, atomically: true, encoding: .utf8)
        let result = try await Command.run(["/usr/bin/osacompile", "-o", folder.appendingPathComponent("tool.scpt").path, source.path], timeout: 30)
        #expect(result.status == 0, "\(result.stderr)")
    }

    @Test func badArgumentsNeverReachAScript() async {
        await #expect(throws: ToolFailure("Avery is not an email address; look it up with contacts_lookup first")) {
            try await AppleScriptTools.mailDraft(["to": ["Avery"], "subject": "Hi"])
        }
        await #expect(throws: ToolFailure.self) {
            try await AppleScriptTools.messagesSend(["to": "Avery", "text": "hi"])
        }
        await #expect(throws: ToolFailure("that is not a note id from notes_search")) {
            try await AppleScriptTools.notesRead(["id": "1 or every note"])
        }
        await #expect(throws: ToolFailure("that is not an email id from mail_search")) {
            try await AppleScriptTools.mailRead(["id": "42"])
        }
    }
}

@Suite("Browsers")
struct BrowserToolTests {
    @Test func tabsFromTheScriptsOutput() {
        let chrome = BrowserTools.browsers[0]
        let output = "1\u{1F}1\u{1F}Inbox\u{1F}https://mail.example.com/u/0/?tab=rm#inbox\u{1F}false\u{1E}"
            + "1\u{1F}2\u{1F}Upload: 63%\u{1F}https://upload.example.com/files?id=9\u{1F}true\u{1E}"
            + "2\u{1F}1\u{1F}Docs\u{1F}https://docs.example.com/\u{1F}true\u{1E}"
        let tabs = BrowserTools.parse(output, browser: chrome)
        #expect(tabs.count == 3)
        #expect(tabs[0].url == "https://mail.example.com/u/0/")  // no query, no fragment
        #expect(tabs[1].id == "chrome:1:2")
        #expect(tabs[1].active)
        #expect(BrowserTools.best(tabs, matching: "upload")?.id == "chrome:1:2")
        #expect(BrowserTools.best(tabs, matching: "example")?.id == "chrome:1:2")  // the front window's active tab first
        #expect(BrowserTools.best(tabs, matching: "docs example")?.id == "chrome:2:1")
        #expect(BrowserTools.best(tabs, matching: "nothing here") == nil)
    }

    /// The scripts of the browsers installed here compile (none is started).
    @Test func scriptsCompile() async throws {
        for browser in BrowserTools.browsers {
            let installed = await MainActor.run { NSWorkspace.shared.urlForApplication(withBundleIdentifier: browser.bundleID) != nil }
            guard installed else { continue }
            for script in [BrowserTools.listScript(browser), BrowserTools.showScript(browser)] {
                let folder = try temporaryFolder()
                let source = folder.appendingPathComponent("tool.applescript")
                try script.write(to: source, atomically: true, encoding: .utf8)
                let result = try await Command.run(["/usr/bin/osacompile", "-o", folder.appendingPathComponent("t.scpt").path, source.path], timeout: 30)
                #expect(result.status == 0, "\(browser.name): \(result.stderr)")
            }
        }
    }

    @Test func unknownBrowsersAreRefused() async {
        await #expect(throws: ToolFailure("I can read Chrome, Safari, Arc, Edge and Brave, not Netscape")) {
            try await BrowserTools.listTabs(["browser": "Netscape"])
        }
        await #expect(throws: ToolFailure("that is not a tab id from browser_tabs")) {
            try await BrowserTools.showTab(["id": "chrome; do shell script"])
        }
    }
}

@Suite("Apps, links and the clipboard")
struct AppToolTests {
    @Test func appNames() {
        let names = ["Safari", "Calendar", "Visual Studio Code", "Calculator", "Notes"]
        #expect(AppTools.bestApp("safari", among: names) == "Safari")
        #expect(AppTools.bestApp("Calc", among: names) == "Calculator")
        #expect(AppTools.bestApp("studio code", among: names) == "Visual Studio Code")
        #expect(AppTools.bestApp("Notes.app", among: names) == "Notes")
        #expect(AppTools.bestApp("Photoshop", among: names) == nil)
    }

    @Test func onlyWebAddresses() {
        #expect(AppTools.webURL("example.com/docs")?.absoluteString == "https://example.com/docs")
        #expect(AppTools.webURL("http://localhost:8765") != nil)
        #expect(AppTools.webURL("file:///etc/passwd") == nil)
        #expect(AppTools.webURL("javascript:alert(1)") == nil)
        #expect(AppTools.webURL("x-apple.systempreferences:com.apple") == nil)
    }

    @Test func promptLinks() {
        let link = AppTools.promptLink(template: "vscode://publisher.extension/open?prompt={prompt}", prompt: "fix the tests & push?")
        #expect(link?.absoluteString == "vscode://publisher.extension/open?prompt=fix%20the%20tests%20%26%20push%3F")
        #expect(AppTools.promptLink(template: "vscode://publisher.extension/open", prompt: "x") == nil)
    }

    @Test func passwordsOnTheClipboardAreNeverRead() {
        #expect(AppTools.isPrivate(["public.utf8-plain-text", "org.nspasteboard.ConcealedType"]))
        #expect(!AppTools.isPrivate(["public.utf8-plain-text"]))
    }

    @Test func commandsRunAndStop() async throws {
        let echo = try await Command.run(["/bin/echo", "hello"])
        #expect(echo.status == 0)
        #expect(echo.stdout == "hello\n")
        let slow = try await Command.run(["/bin/sleep", "5"], timeout: 0.3)
        #expect(slow.timedOut)
        let input = try await Command.run(["/bin/cat"], input: "piped")
        #expect(input.stdout == "piped")
    }
}

@Suite("Pushing a task's branch")
struct PushGuardTests {
    @Test(arguments: ["main", "master", "Main", "refs/heads/main", "-f", "a..b", "x:main", ""])
    func neverPushed(branch: String) {
        #expect(PushGuard.refusal(branch: branch, defaultBranch: nil, protected: false) != nil, "\(branch)")
    }

    @Test func theDefaultBranchIsNeverPushed() {
        #expect(PushGuard.refusal(branch: "trunk", defaultBranch: "trunk", protected: false) != nil)
        #expect(PushGuard.refusal(branch: "ira/task-t1a2b3", defaultBranch: "main", protected: false) == nil)
        #expect(PushGuard.refusal(branch: "feature/x", defaultBranch: "main", protected: false) == nil)
    }

    /// A protected repository (one that deploys when its main branch moves) takes
    /// only Ira's own task branches.
    @Test func protectedRepositories() {
        for branch in ["production", "release", "deploy", "live", "develop", "feature/x"] {
            #expect(PushGuard.refusal(branch: branch, defaultBranch: "main", protected: true) != nil, "\(branch)")
        }
        #expect(PushGuard.refusal(branch: "ira/task-t1a2b3", defaultBranch: "main", protected: true) == nil)
        #expect(PushGuard.refusal(branch: "ira/task-t1a2b3", defaultBranch: "ira/task-t1a2b3", protected: true) != nil)
    }

    @Test func neverForced() {
        let args = PushGuard.pushArguments(branch: "ira/task-t1")
        #expect(args == ["push", "--set-upstream", "origin", "refs/heads/ira/task-t1:refs/heads/ira/task-t1"])
        #expect(!args.contains { $0.contains("force") || $0.hasPrefix("+") || $0 == "-f" })
    }
}

@Suite("Coding tasks", .serialized)
struct CodeTaskTests {
    @Test func settingsFromTasksJSON() throws {
        let home = URL(fileURLWithPath: "/Users/avery")
        let json = """
            {"command": ["agent", "-p", "{prompt}"],
             "repos": {"shop": {"path": "~/code/shop", "test": "make test"}, "site": {"path": "/srv/site", "protected": true},
                       "bad name!": "~/x"},
             "vscode": {"open": false, "promptURI": "vscode://publisher.extension/open?prompt={prompt}"}}
            """
        let settings = try #require(TaskSettings.parse(Data(json.utf8), home: home))
        #expect(settings.repos.keys.sorted() == ["shop", "site"])
        #expect(settings.repos["shop"]?.path.path == "/Users/avery/code/shop")
        #expect(settings.repos["shop"]?.test == "make test")
        #expect(settings.repos["site"]?.protected == true)
        #expect(settings.repos["shop"]?.protected == false)
        #expect(settings.worktrees.path == "/Users/avery/ira-tasks")
        #expect(settings.openVSCode == false)
        #expect(settings.sandbox)
        #expect(TaskSettings.parse(Data(#"{"repos": {"a": "~/a"}}"#.utf8)) == nil)  // no command: not set up
        #expect(CodeTasks.argv(["agent", "-p", "{prompt}", "--json"], prompt: "do it") == ["agent", "-p", "do it", "--json"])
        #expect(CodeTasks.argv(["agent"], prompt: "do it") == ["agent", "do it"])
    }

    @Test func agentProgress() {
        let (text, _) = AgentOutput.progress(#"{"type":"assistant","message":{"content":[{"type":"text","text":"Reading the tests"}]}}"#)
        #expect(text == "Reading the tests")
        let (tool, _) = AgentOutput.progress(#"{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit"}]}}"#)
        #expect(tool == "using Edit")
        let (_, result) = AgentOutput.progress(#"{"type":"result","result":"Fixed it.","is_error":false}"#)
        #expect(result?["result"] == "Fixed it.")
        #expect(AgentOutput.progress("plain words").0 == "plain words")
    }

    /// The sandbox lets the agent write in its worktree and nowhere else in the home folder.
    @Test func theSandboxKeepsTheAgentInItsWorktree() async throws {
        guard FileManager.default.isExecutableFile(atPath: CodeTasks.sandboxExec) else { return }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let root = try temporaryFolder()
        let repo = TaskSettings.Repo(name: "shop", path: root.appendingPathComponent("shop"), test: nil, protected: false)
        let worktree = root.appendingPathComponent("tasks/shop-t1")
        try FileManager.default.createDirectory(at: worktree, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: repo.path.appendingPathComponent(".git"), withIntermediateDirectories: true)
        let job = CodeTasks.Job(id: "t1", repo: repo, instruction: "x", branch: "ira/task-t1", worktree: worktree, base: "HEAD", started: Date())
        let settings = TaskSettings(command: ["agent"], repos: ["shop": repo], worktrees: root.appendingPathComponent("tasks"),
                                    writable: [], minutes: 1, sandbox: true, openVSCode: false, promptURI: nil)
        let tasks = CodeTasks(settings: { settings })
        let outside = home.appendingPathComponent("ira-sandbox-probe-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: outside) }
        let blocked = try await Command.run(tasks.sandboxed(["/usr/bin/touch", outside.path], task: job, settings: settings))
        #expect(blocked.status != 0)
        #expect(!FileManager.default.fileExists(atPath: outside.path))
        let inside = worktree.appendingPathComponent("made-here.txt")
        let allowed = try await Command.run(tasks.sandboxed(["/usr/bin/touch", inside.path], task: job, settings: settings))
        #expect(allowed.status == 0, "\(allowed.stderr)")
        #expect(FileManager.default.fileExists(atPath: inside.path))
    }

    func git(_ folder: URL, _ args: String...) async throws {
        let result = try await Command.run(["/usr/bin/git", "-C", folder.path] + args, timeout: 30)
        #expect(result.status == 0, "git \(args): \(result.stderr)")
    }

    /// A whole task against a real git repository and a scripted "agent": a new
    /// worktree and branch, progress, the files changed, the tests, the done
    /// event, and a push of the task branch only.
    @Test func aWholeTask() async throws {
        let root = try temporaryFolder()
        let remote = root.appendingPathComponent("remote.git")
        let repo = root.appendingPathComponent("shop")
        try FileManager.default.createDirectory(at: repo, withIntermediateDirectories: true)
        _ = try await Command.run(["/usr/bin/git", "init", "--bare", "-b", "main", remote.path])
        try await git(repo, "init", "-b", "main")
        try await git(repo, "config", "user.email", "tests@example.com")
        try await git(repo, "config", "user.name", "Tests")
        try "hello\n".write(to: repo.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
        try await git(repo, "add", ".")
        try await git(repo, "commit", "-m", "Start")
        try await git(repo, "remote", "add", "origin", remote.path)
        try await git(repo, "push", "origin", "main")

        // The "agent": writes a file, tries to push (refused), reports progress and a result.
        let agent = root.appendingPathComponent("agent.sh")
        try """
            #!/bin/sh
            echo '{"type":"assistant","message":{"content":[{"type":"text","text":"Adding the note"}]}}'
            echo "done by the agent" > NOTE.txt
            git add NOTE.txt && git -c user.email=a@example.com -c user.name=Agent commit -qm "Add a note"
            if git push -q origin HEAD 2>/dev/null; then echo PUSHED > PUSHED.txt; fi
            echo '{"type":"result","result":"Added NOTE.txt.","is_error":false}'
            """.write(to: agent, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: agent.path)

        let settings = TaskSettings(
            command: [agent.path], repos: [
                "shop": .init(name: "shop", path: repo, test: "test -f NOTE.txt", protected: false),
            ],
            worktrees: root.appendingPathComponent("tasks"), writable: [], minutes: 1, sandbox: false,
            openVSCode: false, promptURI: nil)
        let events = EventLog<String>()
        let opened = EventLog<URL>()
        let tasks = CodeTasks(
            settings: { settings }, openVSCode: { opened.add($0) },
            announce: { event, title, text, _ in events.add("\(event): \(title): \(text)") })

        let started = try await tasks.start(["repo": "shop", "instruction": "Add a note", "openInVSCode": true])
        let id = try #require(started["id"]?.stringValue)
        let worktree = try #require(started["worktree"]?.stringValue)
        #expect(opened.all.map(\.path) == [worktree])
        #expect(await events.waitFor { !$0.isEmpty })
        let status = try await tasks.status(["id": .string(id)])
        #expect(status["status"] == "done")
        #expect(status["files"] == ["NOTE.txt"])
        #expect(status["tests"] == "passed")
        #expect(status["summary"]?.stringValue?.contains("is done") == true)
        #expect(events.all.first?.hasPrefix("task_done: Task \(id) in shop is done") == true)
        // The agent's own push was refused.
        #expect(!FileManager.default.fileExists(atPath: URL(fileURLWithPath: worktree).appendingPathComponent("PUSHED.txt").path))

        // Pushing, after the PIN, sends the task branch only.
        let pushed = try await tasks.push(["id": .string(id)])
        #expect(pushed["summary"]?.stringValue?.contains("Pushed ira/task-") == true)
        let branches = try await Command.run(["/usr/bin/git", "-C", remote.path, "branch", "--list"])
        #expect(branches.stdout.contains("ira/task-\(id)"))
        let main = try await Command.run(["/usr/bin/git", "-C", remote.path, "log", "--oneline", "main"])
        #expect(main.stdout.split(separator: "\n").count == 1)  // main did not move

        await #expect(throws: ToolFailure.self) { try await tasks.start(["repo": "elsewhere", "instruction": "x"]) }
        let list = try await tasks.list([:])
        #expect(list["repos"] == ["shop"])
    }
}
