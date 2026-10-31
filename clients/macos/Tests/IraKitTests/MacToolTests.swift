import AppKit
import CryptoKit
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
            "reminders_list": "reminders 0", "reminders_set": "reminders 1",
            "mail_search": "mail 0", "mail_draft": "mail 2",
            "messages_send": "messages 2",
            "notes_search": "notes 0", "notes_add": "notes 1",
            "app_open": "apps 1", "url_open": "apps 2",
            "clipboard_read": "clipboard 0",
            "shortcuts_list": "shortcuts 0", "shortcuts_run": "shortcuts 2",
            "mac_type": "control 3", "mac_keys": "control 3", "mac_click": "control 3", "mac_scroll": "control 3",
            "mac_menu": "control 3",
            "code_task_start": "tasks 2", "code_task_status": "tasks 0",
            "code_task_stop": "tasks 1", "code_task_push": "tasks 3",
        ])
    }

    /// An approval window covers the control tools: none may carry a word that
    /// keeps a tool out of it, and each says to prefer a direct tool.
    @Test func controlToolsCanBeCoveredByAnApproval() {
        let never = ["send", "reply", "call", "place", "pay", "buy", "transfer", "delete", "remove", "push", "grant", "pair"]
        for tool in ToolCatalog.control {
            let name = tool["name"]!.stringValue!
            #expect(!never.contains(where: name.contains), "\(name)")
            #expect(name.hasPrefix("mac_"))
            let description = tool["description"]!.stringValue!
            #expect(description.contains("Last resort") && description.contains("url_open"), "\(name)")
            let properties = tool["parameters"]?["properties"]?.objectValue ?? [:]
            #expect(properties["task"] != nil && properties["app"] != nil, "\(name)")
        }
    }

    @Test func toolsThatDoTwoThingsTakeOnlyOnesArguments() throws {
        #expect(throws: ToolFailure.self) { try Toolbox.only(["done": true, "title": "Pay rent", "due": "2026-10-24"], ["id", "title"], what: "marking a reminder done", drop: ["done"]) }
        let done = try Toolbox.only(["done": true, "title": "Pay rent"], ["id", "title"], what: "marking a reminder done", drop: ["done"])
        #expect(done == ["title": "Pay rent"])
        #expect(Toolbox.target("mail_search", ["id": "42"]) == "one email")
        #expect(Toolbox.target("code_task_status", [:]) == "all tasks")
        #expect(Toolbox.target("mac_type", ["text": "lofi music", "app": "Safari"]) == "10 characters in Safari")
        #expect(Toolbox.target("mac_click", ["label": "Subscribe"]) == "“Subscribe”")
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

    @Test func longTasksSayHowTheyAreGoing() {
        let start = Date(timeIntervalSince1970: 1_000_000)
        #expect(!CodeTasks.progressDue(started: start, last: start, now: start.addingTimeInterval(120)))
        #expect(CodeTasks.progressDue(started: start, last: start, now: start.addingTimeInterval(301)))
        let said = start.addingTimeInterval(301)
        #expect(!CodeTasks.progressDue(started: start, last: said, now: said.addingTimeInterval(300)))
        #expect(CodeTasks.progressDue(started: start, last: said, now: said.addingTimeInterval(601)))
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

@Suite("Taking over from the old companion")
struct CompanionTests {
    final class Recorder: @unchecked Sendable {
        private let lock = NSLock()
        private var seen: [[String]] = []
        func add(_ argv: [String]) { lock.withLock { seen.append(argv) } }
        var all: [[String]] { lock.withLock { seen } }
    }

    func install(in home: URL, config: String) throws -> Companion {
        let folder = home.appendingPathComponent("Library/Application Support/ira-mac")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try config.write(to: folder.appendingPathComponent("config.json"), atomically: true, encoding: .utf8)
        let agents = home.appendingPathComponent("Library/LaunchAgents")
        try FileManager.default.createDirectory(at: agents, withIntermediateDirectories: true)
        try "<plist/>".write(to: agents.appendingPathComponent("in.ira.mac.plist"), atomically: true, encoding: .utf8)
        let host = home.appendingPathComponent("Library/Application Support/Google/Chrome/NativeMessagingHosts")
        try FileManager.default.createDirectory(at: host, withIntermediateDirectories: true)
        try "{}".write(to: host.appendingPathComponent("in.ira.mac.json"), atomically: true, encoding: .utf8)
        return Companion(home: home)
    }

    @Test func findsItsSettingsButNeverItsTokenInAFile() throws {
        let home = try temporaryFolder()
        #expect(!Companion(home: home).present)
        let companion = try install(in: home, config: """
            {"server": "https://ira.example.com", "device_id": 7, "label": "Studio Mac", "network_salt": "abc123", "tasks": {}}
            """)
        #expect(companion.present)
        let found = try #require(companion.settings())
        #expect(found == Companion.Found(server: "https://ira.example.com", deviceID: 7, label: "Studio Mac", networkSalt: "abc123", tasks: nil))
    }

    @Test func itsTokenComesFromItsOwnKeychainItem() async throws {
        let recorder = Recorder()
        let token = "irad_" + String(repeating: "k", count: 43)
        let companion = Companion(home: try temporaryFolder()) { argv in
            recorder.add(argv)
            return Command.Result(status: 0, stdout: token + "\n")
        }
        #expect(await companion.token() == token)
        #expect(recorder.all == [["/usr/bin/security", "find-generic-password", "-s", "ira-mac", "-a", "device", "-w"]])
        // Ira for Mac's own item is another service, so the two never collide.
        #expect(KeychainStore().service == "in.ira.mac")
        #expect(Companion.keychainService != KeychainStore().service)
        let bad = Companion(home: try temporaryFolder()) { _ in Command.Result(status: 0, stdout: "not a token") }
        #expect(await bad.token() == nil)
    }

    @Test func removingItTakesEveryPart() async throws {
        let home = try temporaryFolder()
        let recorder = Recorder()
        var companion = try install(in: home, config: #"{"server": "https://ira.example.com"}"#)
        companion = Companion(home: home) { argv in
            recorder.add(argv)
            return Command.Result(status: 0, stdout: "")
        }
        await companion.remove()
        #expect(!companion.present)
        #expect(recorder.all.contains { $0.first == "/bin/launchctl" && $0.last == "gui/\(getuid())/in.ira.mac" })
        #expect(recorder.all.contains(["/usr/bin/security", "delete-generic-password", "-s", "ira-mac", "-a", "device"]))
    }
}

@Suite("Hey Ira")
struct WakePhraseTests {
    @Test(arguments: ["Hey Ira", "hey ira, what's on today", "Okay. Hey, Ira!", "hey eera", "Hi Ira", "hey Irah kya time hai"])
    func heard(text: String) {
        #expect(WakePhrase.heard(text))
    }

    @Test(arguments: ["Ira", "hey there", "pirate", "hey iran news", "they irate"])
    func notHeard(text: String) {
        #expect(!WakePhrase.heard(text))
    }

    @Test func aPhraseOfTheirOwn() {
        #expect(WakePhrase.heard("ok so suno Jarvis please", phrase: "Suno Jarvis"))
        #expect(!WakePhrase.heard("hey ira", phrase: "Suno Jarvis"))
    }
}

@Suite("Confirming with a PIN", .serialized)
struct ConfirmTests {
    @Test func thePinGoesOnlyToTheConfirmStep() async throws {
        let host = "confirm.example.com"
        let session = StubProtocol.session(host: host) { request, body in
            #expect(request.url?.path == "/v1/actions/act_1/confirm")
            #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer irad_test")
            let pin = body.flatMap(JSONValue.parse)?["pin"]?.stringValue
            return pin == "4321"
                ? .init(status: 200, body: Data(#"{"status": "executed", "result": {}}"#.utf8))
                : .init(status: 403, body: Data(#"{"status": "wrong_pin", "attempts_left": 2}"#.utf8))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        #expect(try await client.confirm(actionID: "act_1", pin: "4321")["status"] == "executed")
        let wrong = try await client.confirm(actionID: "act_1", pin: "1111")
        #expect(wrong["status"] == "wrong_pin")
        #expect(wrong["attempts_left"]?.intValue == 2)
    }

    /// The bytes signed are the server's: id, the summary's SHA-256 in hex, the expiry.
    @Test func aSignatureCoversWhatThePersonWasShown() throws {
        let message = ApprovalSignature.message(actionID: "act_7", summary: "Type “lofi” in Safari", expiresAt: 1_792_000_123)
        let digest = SHA256.hash(data: Data("Type “lofi” in Safari".utf8)).map { String(format: "%02x", $0) }.joined()
        #expect(String(decoding: message, as: UTF8.self) == "ira-approve:1\nact_7\n\(digest)\n1792000123")
        #expect(ApprovalSignature.base64url(Data([0xfb, 0xff, 0xfe])) == "-__-")
        // A P-256 key signs it as the server checks it: ECDSA with SHA-256, DER.
        let key = P256.Signing.PrivateKey()
        let signature = try key.signature(for: message).derRepresentation
        let checker = try P256.Signing.PublicKey(derRepresentation: key.publicKey.derRepresentation)
        #expect(checker.isValidSignature(try P256.Signing.ECDSASignature(derRepresentation: signature), for: message))
        #expect(key.publicKey.derRepresentation.count == 91)  // SubjectPublicKeyInfo
    }

    @Test func aSignedConfirmCarriesTheDeviceNotAPin() async throws {
        let host = "signed.example.com"
        let session = StubProtocol.session(host: host) { request, body in
            let json = body.flatMap(JSONValue.parse)
            #expect(json?["pin"] == nil)
            #expect(json?["device_id"]?.intValue == 4)
            #expect(json?["signature"]?.stringValue == "AQID")
            return .init(status: 200, body: Data(#"{"status": "executed"}"#.utf8))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        #expect(try await client.confirm(actionID: "act_2", deviceID: 4, signature: Data([1, 2, 3]))["status"] == "executed")
    }
}

@Suite("Approval windows", .serialized)
struct ApprovalTests {
    @Test func windowsAndTheBanner() {
        let state = Approvals.parse([
            "minutes": 15,
            "windows": [["id": "w1", "device_id": 4, "device": "Studio Mac", "opened_at": 1000, "expires_at": 1900, "steps": 3]],
        ])
        #expect(state.minutes == 15)
        #expect(state.windows == [ApprovalWindow(
            id: "w1", deviceID: 4, device: "Studio Mac", openedAt: Date(timeIntervalSince1970: 1000),
            expiresAt: Date(timeIntervalSince1970: 1900), steps: 3)])
        #expect(Approvals.parse(["windows": [["id": "broken"]]]).windows.isEmpty)
        let trusted = Approvals.parse(["minutes": 0, "windows": [], "trusted_apps": [
            ["device_id": 4, "device": "Studio Mac", "apps": ["com.google.Chrome", "com.apple.Music"]],
            ["device_id": 7, "device": "Phone", "apps": ["com.google.android.youtube"]],
        ]])
        #expect(trusted.trustedApps[4] == ["com.google.Chrome", "com.apple.Music"])
        #expect(trusted.trustedApps[9] == nil)
        #expect(Approvals.manageLink(server: "https://ira.example.com/")?.absoluteString == "https://ira.example.com/#panel=assistant")
        #expect(Approvals.banner(remaining: 12 * 60) == "Ira can control this Mac for 12 more minutes")
        #expect(Approvals.banner(remaining: 11 * 60 + 5) == "Ira can control this Mac for 12 more minutes")
        #expect(Approvals.banner(remaining: 61) == "Ira can control this Mac for 2 more minutes")
        #expect(Approvals.banner(remaining: 60) == "Ira can control this Mac for 1 more minute")
        #expect(Approvals.banner(remaining: 20) == "Ira can control this Mac for less than a minute more")
        #expect(Approvals.covers("mac_click") && Approvals.covers("screen_read") && Approvals.covers("url_open"))
        #expect(!Approvals.covers("messages_send") && !Approvals.covers("files_find"))
    }

    @Test func aDeviceStopsAWindowButNeverOpensOne() async throws {
        let host = "approvals.example.com"
        let session = StubProtocol.session(host: host) { request, _ in
            switch (request.httpMethod ?? "", request.url?.path ?? "") {
            case ("GET", "/v1/me/approvals"):
                return .init(status: 200, body: Data(#"{"minutes": 15, "windows": []}"#.utf8))
            case ("DELETE", "/v1/me/approvals/w1"), ("DELETE", "/v1/me/approvals"):
                return .init(status: 200, body: Data(#"{"ok": true}"#.utf8))
            default:
                return .init(status: 404, body: Data(#"{"detail": "not here"}"#.utf8))
            }
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        #expect(Approvals.parse(try await client.approvals()).minutes == 15)
        try await client.stopApproval("w1")
        try await client.stopApproval(nil)
        let methods = StubProtocol.requests(host).map { "\($0.0.httpMethod ?? "") \($0.0.url?.path ?? "")" }
        #expect(methods == ["GET /v1/me/approvals", "DELETE /v1/me/approvals/w1", "DELETE /v1/me/approvals"])
    }

    @Test func enrollingSendsThePublicKeyAndThePin() async throws {
        let host = "enrol.example.com"
        let key = P256.Signing.PrivateKey().publicKey.derRepresentation
        let session = StubProtocol.session(host: host) { request, body in
            #expect(request.url?.path == "/v1/me/approval-keys")
            let json = body.flatMap(JSONValue.parse)
            #expect(json?["algorithm"] == "ES256")
            #expect(json?["pin"] == "4321")
            #expect(json?["public_key"]?.stringValue.flatMap { Data(base64Encoded: $0) } == key)
            return .init(status: 200, body: Data(#"{"device_id": 4, "device": "Studio Mac", "algorithm": "ES256", "created_at": 1}"#.utf8))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        #expect(try await client.enrolApprovalKey(publicKey: key, pin: "4321")["device_id"]?.intValue == 4)
    }
}

/// An element tree standing in for another app's window.
final class FakeNode: MacControl.Node {
    let role: String
    let subrole: String?
    let names: [String]
    let enabled: Bool
    let actions: [String]
    let frame: CGRect?
    var nodes: [FakeNode]

    init(_ role: String, _ names: [String] = [], subrole: String? = nil, enabled: Bool = true,
         actions: [String] = [], y: CGFloat = 0, _ nodes: [FakeNode] = []) {
        self.role = role
        self.subrole = subrole
        self.names = names
        self.enabled = enabled
        self.actions = actions
        self.frame = CGRect(x: 10, y: y, width: 80, height: 20)
        self.nodes = nodes
    }

    func isSame(_ other: FakeNode) -> Bool { self === other }
}

@Suite("Using the Mac like a person")
struct ControlTests {
    @Test func keysAndShortcuts() throws {
        let presses = try MacControl.parseKeys("cmd+L, cmd+shift+t  return")
        #expect(presses.map(\.spoken) == ["Command-L", "Command-Shift-T", "Return"])
        #expect(presses[0].code == CGKeyCode(0x25))
        #expect(presses[0].flags == CGEventFlags.maskCommand.rawValue)
        #expect(presses[1].flags == CGEventFlags([.maskCommand, .maskShift]).rawValue)
        #expect(try MacControl.parseKeys("down down esc").map(\.spoken) == ["Down", "Down", "Escape"])
        #expect(try MacControl.parseKeys("cmd++").map(\.spoken) == ["Command-="])
        #expect(try MacControl.parseKeys("f5 option+delete").map(\.spoken) == ["F5", "Option-Delete"])
        #expect(throws: ToolFailure.self) { try MacControl.parseKeys("hyper+x") }
        #expect(throws: ToolFailure.self) { try MacControl.parseKeys("cmd+printscreen") }
        #expect(throws: ToolFailure.self) { try MacControl.parseKeys(Array(repeating: "down", count: 13).joined(separator: " ")) }
        #expect(throws: ToolFailure.self) { try MacControl.parseKeys("  ") }
    }

    @Test func aControlIsFoundByItsLabel() throws {
        let field = FakeNode("AXTextField", ["Search"], y: 10)
        let search = FakeNode("AXButton", [], actions: ["AXPress"], y: 10, [FakeNode("AXStaticText", ["Search"])])
        let subscribe = FakeNode("AXButton", ["Subscribe…"], actions: ["AXPress"], y: 300)
        let window = FakeNode("AXWindow", ["YouTube"], [
            FakeNode("AXGroup", [], [field, search]),
            FakeNode("AXGroup", [], [FakeNode("AXStaticText", ["Subscribers"]), subscribe]),
        ])
        // The text inside a button counts as the button's.
        let both = MacControl.find("search", role: nil, in: window)
        #expect(both.count == 2)
        #expect(MacControl.find("search", role: "button", in: window).first?.node === search)
        #expect(MacControl.find("Search", role: "field", in: window).first?.node === field)
        // An ellipsis and case do not matter; a longer word is not the label.
        let found = MacControl.find("subscribe", role: nil, in: window)
        #expect(found.count == 1 && found.first?.node === subscribe)
        #expect(MacControl.find("upload", role: nil, in: window).isEmpty)
        // Words with no control around them are a last resort, clicked where they are.
        let words = MacControl.find("subscribers", role: nil, in: window)
        #expect(words.count == 1 && words.first?.actionable == false)
        #expect(MacControl.find("subscribers", role: "button", in: window).isEmpty)
        // Two equally good matches: Ira asks which, and index picks one top to bottom.
        guard case .failure(let failure) = MacControl.choose(both, index: nil) else { Issue.record("should ask"); return }
        #expect(failure.message.contains("2 controls called “Search”"))
        guard case .success(let second) = MacControl.choose(both, index: 2) else { Issue.record("index"); return }
        #expect(second.node === field || second.node === search)
        guard case .failure = MacControl.choose(both, index: 3) else { Issue.record("out of range"); return }
    }

    @Test func betterNamesAndEnabledControlsComeFirst() {
        let exact = FakeNode("AXButton", ["Play"], actions: ["AXPress"], y: 200)
        let longer = FakeNode("AXButton", ["Play all"], actions: ["AXPress"], y: 100)
        let greyed = FakeNode("AXButton", ["Play"], enabled: false, actions: ["AXPress"], y: 50)
        let window = FakeNode("AXWindow", [], [greyed, longer, exact])
        let found = MacControl.find("play", role: nil, in: window)
        #expect(found.map(\.node).first === exact)
        #expect(found[1].node === greyed)
        #expect(found[2].node === longer)
        guard case .success(let chosen) = MacControl.choose(found, index: nil) else { Issue.record("one best"); return }
        #expect(chosen.node === exact)
    }

    @Test func whereIraNeverActs() {
        #expect(MacControl.refusal(bundleID: "in.ira.mac", app: "Ira", window: nil) != nil)
        #expect(MacControl.refusal(bundleID: "com.1password.1password", app: "1Password", window: nil)?.contains("passwords") == true)
        #expect(MacControl.refusal(bundleID: "com.apple.systempreferences", app: "System Settings", window: "Privacy & Security") != nil)
        #expect(MacControl.refusal(bundleID: "com.apple.systempreferences", app: "System Settings", window: "Users & Groups") != nil)
        #expect(MacControl.refusal(bundleID: "com.apple.systempreferences", app: "System Settings", window: nil) != nil)
        #expect(MacControl.refusal(bundleID: "com.apple.systempreferences", app: "System Settings", window: "Appearance") == nil)
        #expect(MacControl.refusal(bundleID: "com.apple.Safari", app: "Safari", window: "YouTube") == nil)
        // Whatever is typed there runs as a command, whatever the server says.
        for (id, app) in [("com.apple.Terminal", "Terminal"), ("com.apple.shortcuts", "Shortcuts"),
                          ("com.apple.ScriptEditor2", "Script Editor"), ("com.github.wez.wezterm", "WezTerm")] {
            #expect(MacControl.refusal(bundleID: id, app: app, window: nil) == NeverApps.refusal, "\(app)")
        }
        #expect(!NeverApps.contains(bundleID: "com.apple.Notes", name: "Notes"))
        let policy = PathPolicy(home: FileManager.default.homeDirectoryForCurrentUser)
        #expect(Toolbox.openRefusal("/System/Applications/Utilities/Terminal.app", policy: policy) == NeverApps.refusal)
        #expect(Toolbox.openRefusal("/System/Applications/Shortcuts.app", policy: policy) == NeverApps.refusal)
        #expect(Toolbox.openRefusal("/System/Applications/Notes.app", policy: policy) == nil)
        #expect(MacControl.isSecure(role: "AXTextField", subrole: "AXSecureTextField"))
        #expect(MacControl.isSecure(role: "AXSecureTextField", subrole: nil))
        #expect(!MacControl.isSecure(role: "AXTextField", subrole: "AXSearchField"))
    }

    @Test func menuPaths() throws {
        #expect(try MacControl.menuPath("File > New Window") == ["File", "New Window"])
        #expect(try MacControl.menuPath("View → Sort By > Name") == ["View", "Sort By", "Name"])
        #expect(throws: ToolFailure.self) { try MacControl.menuPath("File") }
        #expect(throws: ToolFailure.self) { try MacControl.menuPath("Apple > Restart…") }
        #expect(MacControl.pick("new window", among: ["New Tab", "New Window", "New Private Window"]) == 1)
        #expect(MacControl.pick("Export", among: ["Export as PDF…", "Export…"]) == 1)
        #expect(MacControl.pick("New", among: ["New Tab", "New Window"]) == nil)
        #expect(MacControl.pick("Show Sidebar", among: ["Show Sidebar…"]) == 0)
    }

    @Test func wordsOnScreenBecomeAPoint() {
        let frame = CGRect(x: 100, y: 50, width: 800, height: 600)
        let point = ScreenText.point(of: CGRect(x: 0.5, y: 0.75, width: 0.1, height: 0.1), in: frame)
        #expect(point == CGPoint(x: 100 + 0.55 * 800, y: 50 + (1 - 0.8) * 600))
    }

    @Test func withoutAccessibilityItSaysWhere() async {
        // Tests run without Accessibility: every control tool answers with where to switch it on.
        guard !MacControl.trusted else { return }
        MacControl.mayPrompt = false
        let toolbox = Toolbox(policy: { PathPolicy(home: FileManager.default.temporaryDirectory) }, frontApp: { nil },
                              log: IraLog(directory: nil), record: { _ in })
        for name in ["mac_type", "mac_keys", "mac_click", "mac_scroll", "mac_menu"] {
            let args: JSONValue = switch name {
            case "mac_type": ["text": "hello"]
            case "mac_keys": ["keys": "return"]
            case "mac_click": ["label": "OK"]
            case "mac_scroll": ["direction": "down"]
            default: ["path": "File > New Window"]
            }
            do {
                _ = try await toolbox.call(name, args: args)
                Issue.record("\(name) ran without Accessibility")
            } catch let failure as ToolFailure {
                #expect(failure.message == MacControl.notTrusted, "\(name)")
            } catch {
                Issue.record("\(name): \(error)")
            }
        }
    }
}
