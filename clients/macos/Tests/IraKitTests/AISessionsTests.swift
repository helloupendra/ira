import Foundation
import Testing
@testable import IraKit

/// Transcript lines written for these tests, in the shape a coding agent writes them.
enum TranscriptLines {
    static let start = Date(timeIntervalSince1970: 1_800_000_000)

    static func time(_ seconds: Double) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: start.addingTimeInterval(seconds))
    }

    static func line(_ value: JSONValue) -> String { value.encoded() }

    static func user(_ text: String, at: Double = 0, origin: String? = "human", extra: [String: JSONValue] = [:]) -> String {
        var entry: [String: JSONValue] = [
            "type": "user", "cwd": "/work/clinic-site", "entrypoint": "ide-vscode", "timestamp": .string(time(at)),
            "message": ["role": "user", "content": .string(text)],
        ]
        if let origin { entry["origin"] = ["kind": .string(origin)] }
        for (key, value) in extra { entry[key] = value }
        return line(.object(entry))
    }

    static func assistant(_ parts: [JSONValue], stop: String, at: Double = 0, entrypoint: String = "ide-vscode") -> String {
        line([
            "type": "assistant", "cwd": "/work/clinic-site", "entrypoint": .string(entrypoint), "timestamp": .string(time(at)),
            "message": ["role": "assistant", "content": .array(parts), "stop_reason": .string(stop)],
        ])
    }

    static func text(_ text: String) -> JSONValue { ["type": "text", "text": .string(text)] }

    static func tool(_ name: String, _ input: JSONValue, id: String = "tu1") -> JSONValue {
        ["type": "tool_use", "id": .string(id), "name": .string(name), "input": input]
    }

    static func result(_ id: String, _ text: String, at: Double = 0) -> String {
        line([
            "type": "user", "cwd": "/work/clinic-site", "timestamp": .string(time(at)),
            "message": ["role": "user", "content": [["type": "tool_result", "tool_use_id": .string(id), "content": .string(text)]]],
        ])
    }

    static func todos(_ items: [(String, String)]) -> JSONValue {
        ["todos": .array(items.map { ["content": .string($0.0), "activeForm": .string("Doing: \($0.0)"), "status": .string($0.1)] })]
    }

    static func summary(_ lines: [String], quiet: Double = 10) -> AISession? {
        TranscriptSummary.summarise(lines: lines, id: "a1b2c3d4-0000", modified: start, now: start.addingTimeInterval(quiet))
    }
}

/// Made-up secrets, put together at run time so no key-shaped text sits in the source.
enum Fake {
    static let aws = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    static let jwt = ["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0In0", "c2lnbmF0dXJlLXZhbHVl"].joined(separator: ".")
    static let pem = ["-----BEGIN RSA PRIV", "ATE KEY-----\nMIIEow\nabc\n-----END RSA PRIV", "ATE KEY-----"].joined()
    static let login = "https://" + "user" + ":" + "pw" + "@example.com/a?token=x#y"
}

@Suite("AI sessions")
struct AISessionsTests {
    typealias T = TranscriptLines

    @Test func aWorkingSessionWithItsTodoList() throws {
        let lines = [
            T.line(["type": "ai-title", "aiTitle": "Invoice total fix", "sessionId": "a1"]),
            T.user("Fix the invoice total for Sunrise Dental Clinic and add tests"),
            T.assistant([T.text("I'll start with the tests.")], stop: "tool_use"),
            T.assistant([T.tool("TodoWrite", T.todos([("write tests", "completed"), ("fix the total", "in_progress"), ("update docs", "pending")]))], stop: "tool_use"),
            T.result("tu1", "Todos have been modified"),
            T.assistant([T.tool("Read", ["file_path": "/work/clinic-site/src/invoice.py"], id: "tu2")], stop: "tool_use"),
            T.result("tu2", "def total(): ..."),
            T.assistant([T.tool("Bash", ["command": "pytest -q tests/test_invoice.py", "description": "Run the invoice tests"], id: "tu3")], stop: "tool_use"),
        ]
        let session = try #require(T.summary(lines))
        #expect(session.project == "clinic-site")
        #expect(session.place == "VS Code")
        #expect(session.title == "Invoice total fix")
        #expect(session.state == .working)
        #expect(session.done == 1 && session.total == 3)
        #expect(session.current == "Doing: fix the total")
        #expect(session.doing == "Run the invoice tests")
        #expect(session.request == "Fix the invoice total for Sunrise Dental Clinic and add tests")
        #expect(session.answer == "I'll start with the tests.")
        #expect(session.steps.map(\.text).contains("read invoice.py"))
        // Never the command, a path or a tool's output.
        let all = session.steps.map(\.text).joined(separator: " ")
        #expect(!all.contains("pytest") && !all.contains("/work/") && !all.contains("def total"))
    }

    @Test func theTaskToolsCountToo() throws {
        let lines = [
            T.user("Tidy the booking page"),
            T.assistant([T.tool("TaskCreate", ["subject": "Move the form", "activeForm": "Moving the form"], id: "c1")], stop: "tool_use"),
            T.result("c1", "Task #1 created successfully: Move the form"),
            T.assistant([T.tool("TaskCreate", ["subject": "Check phones"], id: "c2")], stop: "tool_use"),
            T.result("c2", "Task #2 created successfully: Check phones"),
            T.assistant([T.tool("TaskCreate", ["subject": "Old idea"], id: "c3")], stop: "tool_use"),
            T.result("c3", "Task #3 created successfully: Old idea"),
            T.assistant([T.tool("TaskUpdate", ["taskId": "1", "status": "completed"], id: "u1")], stop: "tool_use"),
            T.assistant([T.tool("TaskUpdate", ["taskId": "3", "status": "deleted"], id: "u2")], stop: "tool_use"),
            T.assistant([T.tool("TaskUpdate", ["taskId": "2", "status": "in_progress", "activeForm": "Checking phones"], id: "u3")], stop: "tool_use"),
        ]
        let session = try #require(T.summary(lines))
        #expect(session.done == 1 && session.total == 2)
        #expect(session.current == "Checking phones")
        #expect(session.doing == "updated its task list")
    }

    @Test func theNewerListWins() throws {
        let created = [
            T.assistant([T.tool("TaskCreate", ["subject": "One"], id: "c1")], stop: "tool_use"),
            T.result("c1", "Task #1 created successfully: One"),
        ]
        let todo = T.assistant([T.tool("TodoWrite", T.todos([("a", "completed"), ("b", "completed")]), id: "w1")], stop: "tool_use")
        let todosLast = try #require(T.summary([T.user("go")] + created + [todo]))
        #expect(todosLast.done == 2 && todosLast.total == 2)
        let tasksLast = try #require(T.summary([T.user("go"), todo] + created))
        #expect(tasksLast.done == 0 && tasksLast.total == 1)
    }

    @Test func statesFromHowTheTranscriptEnds() throws {
        let asked = T.user("Rename the clinic's booking button")
        let ended = T.assistant([T.text("Renamed it.")], stop: "end_turn")
        #expect(T.summary([asked, ended], quiet: 60)?.state == .waiting)
        #expect(T.summary([asked, ended], quiet: 2 * 3600)?.state == .finished)
        let headless = T.assistant([T.text("Done.")], stop: "end_turn", entrypoint: "sdk-cli")
        #expect(T.summary([asked, headless], quiet: 60)?.state == .finished)
        #expect(T.summary([asked, headless], quiet: 60)?.place == "headless")

        let step = T.assistant([T.tool("Bash", ["command": "make", "description": "Build the site"])], stop: "tool_use")
        #expect(T.summary([asked, step], quiet: 30)?.state == .working)
        let quiet = try #require(T.summary([asked, step], quiet: 600))
        #expect(quiet.state == .working)
        #expect(quiet.note?.hasPrefix("quiet for 10 min") == true)
        #expect(T.summary([asked, step], quiet: 2 * 3600)?.state == .finished)

        let question = T.assistant([T.tool("AskUserQuestion", ["questions": []])], stop: "tool_use")
        let waiting = try #require(T.summary([asked, question], quiet: 30))
        #expect(waiting.state == .waiting && waiting.note == "asked you a question")

        let stopped = T.user("[Request interrupted by user]", origin: nil)
        #expect(T.summary([asked, step, stopped], quiet: 30)?.state == .waiting)
        #expect(T.summary([asked], quiet: 30)?.state == .working)
        #expect(T.summary([asked], quiet: 900)?.state == .finished)
    }

    @Test func onlyThePersonsOwnWordsAreTheirRequest() throws {
        let lines = [
            T.user("Add a holiday banner to the home page"),
            T.user("<system-reminder>internal note</system-reminder>Make it green too <ide_selection>selected code</ide_selection>"),
            T.user("<task-notification>a job finished</task-notification>", origin: "task-notification"),
            T.user("a message from another session", origin: "peer"),
            T.user("Caveat: injected", origin: nil, extra: ["isMeta": true]),
            T.user("This session continues from an earlier one…", extra: ["isCompactSummary": true]),
            T.assistant([T.text("Adding it.")], stop: "end_turn"),
        ]
        let session = try #require(T.summary(lines))
        #expect(session.request == "Make it green too")
    }

    @Test func excerptsAreShortAndMasked() throws {
        let key = "sk-ant-api03-" + String(repeating: "Zx9", count: 12)
        let lines = [
            T.user("Use the key \(key) and password=hunter2 to deploy " + String(repeating: "then check again ", count: 30)),
            T.assistant([T.text("The AWS key \(Fake.aws) is in the config; token: abc123def is set.")], stop: "tool_use"),
            T.assistant([T.tool("Bash", ["command": "curl -H 'Authorization: Bearer x'", "description": .string("Call the API with ghp_" + String(repeating: "a1", count: 15))])], stop: "tool_use"),
        ]
        let session = try #require(T.summary(lines))
        let request = try #require(session.request)
        #expect(request.count <= TranscriptSummary.excerpt)
        #expect(!request.contains("Zx9Zx9") && !request.contains("hunter2"))
        #expect(request.contains("password=***"))
        let answer = try #require(session.answer)
        #expect(!answer.contains(Fake.aws) && !answer.contains("abc123def"))
        #expect(session.doing?.contains("ghp_a1a1") == false)
    }

    @Test func noConversationNoSession() {
        #expect(T.summary([T.line(["type": "ai-title", "aiTitle": "x"]), "not json", ""]) == nil)
    }

    @Test func phrasesNameTheKindOfStepNeverItsContents() {
        #expect(TranscriptSummary.phrase("Edit", ["file_path": "/a/b/Booking.swift", "old_string": "x"]) == "edited Booking.swift")
        #expect(TranscriptSummary.phrase("Bash", ["command": "rm -rf build"]) == "ran a command")
        #expect(TranscriptSummary.phrase("WebFetch", ["url": "https://example.com/a?b=c"]) == "read a web page (example.com)")
        #expect(TranscriptSummary.phrase("Agent", ["description": "Review the diff", "prompt": "secret plan"]) == "started a helper: Review the diff")
        #expect(TranscriptSummary.phrase("mcp__calendar__list_events", [:]) == "used calendar")
        #expect(TranscriptSummary.phrase("SomethingNew", [:]) == "used SomethingNew")
    }

    @Test func theTailOfABigFile() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("ira-tail-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("s.jsonl")
        try (1...1000).map { "{\"n\": \($0)}" }.joined(separator: "\n").write(to: file, atomically: true, encoding: .utf8)
        let tail = TailReader.lines(file, bytes: 100)
        #expect(!tail.whole)
        #expect(tail.lines.last == "{\"n\": 1000}")
        #expect(tail.lines.allSatisfy { $0.hasPrefix("{\"n\": ") })
        #expect(TailReader.lines(file, bytes: 1 << 20).whole)
    }

    /// A transcript of tens of megabytes, as real ones are: the first read takes the last 1 MB
    /// (4 MB at most), an unchanged file is not read again, and a grown one only from where it
    /// was left.
    @Test func bigTranscriptsAreReadOnceAndOnlyFromTheEnd() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ira-big-\(UUID().uuidString)")
        let project = root.appendingPathComponent("projects/-work-clinic-site")
        try FileManager.default.createDirectory(at: project, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let output = String(repeating: "x", count: 200_000)
        var lines = [T.user("An early request, far back")]
        for index in 0..<120 {
            lines.append(T.assistant([T.tool("Bash", ["description": .string("Step \(index)")], id: "b\(index)")], stop: "tool_use"))
            lines.append(T.result("b\(index)", output))
        }
        let big = project.appendingPathComponent("b1b1b1b1-0000.jsonl")
        try (lines + [T.user("Check the booking form"), T.assistant([T.text("Checking.")], stop: "tool_use")])
            .joined(separator: "\n").appending("\n").write(to: big, atomically: true, encoding: .utf8)
        // The request is only at the start, 24 MB back: the session is told without it.
        let far = project.appendingPathComponent("f2f2f2f2-0000.jsonl")
        try (lines + [T.assistant([T.text("Still on it.")], stop: "tool_use")])
            .joined(separator: "\n").appending("\n").write(to: far, atomically: true, encoding: .utf8)

        let sessions = AISessions(roots: { [root.appendingPathComponent("projects")] }, worktrees: { nil })
        var started = Date()
        let cold = try await sessions.list([:])
        let coldTime = Date().timeIntervalSince(started)
        let shown = cold["sessions"]?.arrayValue ?? []
        #expect(shown.count == 2)
        let byID = Dictionary(uniqueKeysWithValues: shown.compactMap { s in s["id"]?.stringValue.map { ($0, s) } })
        #expect(byID["b1b1b1b1-0000"]?["request"] == "Check the booking form")
        #expect(byID["f2f2f2f2-0000"]?["request"] == nil)
        #expect(byID["f2f2f2f2-0000"]?["doing"] == "Step 119")
        #expect(coldTime < 5, "cold read took \(coldTime) s")

        started = Date()
        _ = try await sessions.list([:])
        let warmTime = Date().timeIntervalSince(started)
        #expect(warmTime < 1, "an unchanged read took \(warmTime) s")

        let handle = try FileHandle(forWritingTo: big)
        try handle.seekToEnd()
        try handle.write(contentsOf: Data((T.user("Now the footer") + "\n" + T.assistant([T.text("Done.")], stop: "end_turn") + "\n").utf8))
        try handle.close()
        started = Date()
        let grown = try await sessions.list([:])
        #expect(Date().timeIntervalSince(started) < 1)
        let again = grown["sessions"]?.arrayValue?.first { $0["id"] == "b1b1b1b1-0000" }
        #expect(again?["request"] == "Now the footer" && again?["state"] == "waiting")
    }

    @Test func aLineStillBeingWrittenWaitsForTheRest() throws {
        let (lines, used) = TailReader.split(Data("{\"a\":1}\n{\"b\":2}\n{\"c\":".utf8))
        #expect(lines.count == 2 && used == 16)
        let (whole, all) = TailReader.split(Data("{\"a\":1}\n{\"b\":2}".utf8))
        #expect(whole.count == 2 && all == 15)
        #expect(JSONValue.quick(Data(#"{"x": [true, 1.5, null, "s"]}"#.utf8)) == ["x": [true, 1.5, nil, "s"]])
    }

    @Test func theToolsListAndDetailFromTheFolder() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ira-agents-\(UUID().uuidString)")
        let worktrees = root.appendingPathComponent("tasks")
        let project = root.appendingPathComponent("projects/-work-clinic-site")
        let taskProject = root.appendingPathComponent("projects/-tasks-shop-t1a2b3")
        for folder in [project, taskProject, worktrees] { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
        defer { try? FileManager.default.removeItem(at: root) }
        let now = Date()
        func write(_ folder: URL, _ name: String, _ lines: [String], age: Double) throws {
            let file = folder.appendingPathComponent(name)
            try lines.joined(separator: "\n").write(to: file, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.modificationDate: now.addingTimeInterval(-age)], ofItemAtPath: file.path)
        }
        try write(project, "a1b2c3d4-1111.jsonl", [T.user("Fix the footer"), T.assistant([T.text("Fixed.")], stop: "end_turn")], age: 120)
        try write(project, "old0old0-2222.jsonl", [T.user("Old work")], age: 30 * 3600)
        let inTask = T.user("Add a test").replacingOccurrences(of: "/work/clinic-site", with: worktrees.path + "/shop-t1a2b3")
        try write(taskProject, "e5f6a7b8-3333.jsonl", [inTask], age: 5)

        let sessions = AISessions(roots: { [root.appendingPathComponent("projects")] }, worktrees: { worktrees }, now: { now })
        let list = try await sessions.list([:])
        let shown = list["sessions"]?.arrayValue ?? []
        #expect(shown.count == 2)
        #expect(shown.first?["place"] == "Ira's task t1a2b3")
        #expect(shown.first?["project"] == "shop")
        #expect(shown.first?["startedByIra"] == true)
        #expect(shown.last?["state"] == "waiting")
        #expect(list["summary"]?.stringValue?.hasPrefix("2 AI sessions on this Mac in the last 12 hours.") == true)
        #expect(list["control"]?.stringValue?.contains("Ira never sends to or stops a session it did not start") == true)
        #expect(shown.last?["talk"] == false)

        let detail = try await sessions.detail(["id": "a1b2"])
        #expect(detail["id"] == "a1b2c3d4-1111")
        #expect(detail["steps"]?.arrayValue?.map { $0["text"]?.stringValue ?? "" } == ["you asked: Fix the footer", "said: Fixed."])
        await #expect(throws: ToolFailure.self) { try await sessions.detail(["id": "nope"]) }
        await #expect(throws: ToolFailure.self) { try await sessions.list(["path": "/etc"]) }

        let none = try await AISessions(roots: { [root.appendingPathComponent("missing")] }, worktrees: { nil }, now: { now }).list(["hours": 2])
        #expect(none["summary"] == "No AI coding sessions on this Mac in the last 2 hours.")
        let unset = try await AISessions(roots: { [] }, worktrees: { nil }, now: { now }).list([:])
        #expect(unset["summary"]?.stringValue?.contains("listed in tasks.json") == true)
    }
}

@Suite("Secret filter")
struct SecretFilterTests {
    @Test func masksKeysTokensAndPasswords() {
        let samples = [
            Fake.aws,
            "ghp_" + String(repeating: "Ab1", count: 12),
            "github_pat_" + String(repeating: "Ab1_", count: 10),
            "sk-ant-api03-" + String(repeating: "Q1w", count: 10),
            "sk-proj-" + String(repeating: "Q1w", count: 10),
            "xoxb-1234567890-abcdefghij",
            "AIza" + String(repeating: "Sy1", count: 12),
            "sk_live_" + String(repeating: "Ab1", count: 6),
            Fake.jwt,
            "irad_abcdefghijklmnop",
            String(repeating: "aZ9", count: 12),
        ]
        for sample in samples {
            #expect(!SecretFilter.mask("value \(sample) end").contains(sample), "\(sample)")
        }
        let pem = Fake.pem
        #expect(SecretFilter.mask("key: \(pem) done") == "key: [private key] done")
        #expect(SecretFilter.mask("password=hunter22 and DB_PASSWORD: \"s3cret!\"") == "password=*** and DB_PASSWORD: \"***\"")
        #expect(SecretFilter.mask(Fake.login) == "https://***@example.com/a")
        #expect(SecretFilter.mask("Authorization: Bearer abc.def") == "Authorization: Bearer ***")
    }

    @Test func leavesOrdinaryWordsAlone() {
        let text = "Commit 3f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39 fixed the-invoice-total-for-the-clinic in ~/code/site/src/Invoice.swift; 4 tokens left, spin=3"
        #expect(SecretFilter.mask(text) == text)
    }
}
