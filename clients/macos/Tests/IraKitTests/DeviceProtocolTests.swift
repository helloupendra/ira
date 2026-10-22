import Foundation
import Testing
@testable import IraKit

@Suite("Device frames")
struct DeviceFrameTests {
    @Test func welcome() throws {
        let frame = try DeviceProtocol.decode(
            #"{"type":"welcome","deviceId":3,"label":"Studio Mac","skills":["files"],"assistant":"Ira","wakePhrase":"Hey Ira"}"#)
        #expect(frame == .welcome(deviceID: 3, label: "Studio Mac", skills: ["files"], assistant: "Ira"))
    }

    @Test func call() throws {
        let frame = try DeviceProtocol.decode(#"{"type":"call","id":"9b0c","tool":"file_read","args":{"path":"~/a.txt"}}"#)
        #expect(frame == .call(id: "9b0c", tool: "file_read", args: ["path": "~/a.txt"]))
        let bare = try DeviceProtocol.decode(#"{"type":"call","id":"1","tool":"screen_read","args":null}"#)
        #expect(bare == .call(id: "1", tool: "screen_read", args: .object([:])))
    }

    @Test func pingPongSkillsError() throws {
        #expect(try DeviceProtocol.decode(#"{"type":"ping"}"#) == .ping)
        #expect(try DeviceProtocol.decode(#"{"type":"pong"}"#) == .pong)
        #expect(try DeviceProtocol.decode(#"{"type":"skills","skills":["files","screen"]}"#) == .skills(["files", "screen"]))
        #expect(try DeviceProtocol.decode(#"{"type":"error","error":"bad hello"}"#) == .error("bad hello"))
        #expect(try DeviceProtocol.decode(#"{"type":"later"}"#) == .other("later"))
    }

    @Test(arguments: [
        "not json",
        "[1, 2]",
        #"{"no": "type"}"#,
        #"{"type": 3}"#,
        #"{"type": "call", "tool": "x"}"#,
        #"{"type": "call", "id": "1"}"#,
    ])
    func badFrames(text: String) {
        #expect(throws: DeviceProtocol.BadFrame.self) { try DeviceProtocol.decode(text) }
    }

    @Test func framesOver1MBAreRefused() {
        let big = #"{"type":"ping","x":""# + String(repeating: "a", count: 1024 * 1024) + #""}"#
        #expect(throws: DeviceProtocol.BadFrame(reason: "frames are 1 MB at most")) { try DeviceProtocol.decode(big) }
    }

    @Test func helloSaysWhoAndWhat() {
        let hello = DeviceProtocol.hello(label: "Studio Mac", tools: Toolbox.definitions)
        #expect(hello["type"] == "hello")
        #expect(hello["kind"] == "mac")
        #expect(hello["label"] == "Studio Mac")
        #expect(hello["version"]?.stringValue == IraApp.version)
        #expect(hello["tools"]?.arrayValue?.count == Toolbox.definitions.count)
    }

    @Test func resultsAndFailures() {
        #expect(DeviceProtocol.result(id: "1", content: ["summary": "ok"]) == ["type": "result", "id": "1", "ok": true, "content": ["summary": "ok"]])
        let failure = DeviceProtocol.failure(id: "1", error: String(repeating: "e", count: 400))
        #expect(failure["ok"] == false)
        #expect(failure["error"]?.stringValue?.count == 300)
    }

    @Test func anAnswerOver1MBBecomesAnError() throws {
        let huge = DeviceProtocol.result(id: "7", content: .string(String(repeating: "a", count: 1024 * 1024)))
        let text = DeviceProtocol.encodeResult(huge)
        let sent = try #require(JSONValue.parse(text))
        #expect(sent == ["type": "result", "id": "7", "ok": false, "error": "the answer was larger than 1 MB"])
    }
}

/// Tools for the client tests: one that answers, one that fails, one that waits.
struct ScriptedTools: ToolRunner {
    var definitions: [JSONValue] { [["name": "echo_back", "description": "Echo.", "parameters": ["type": "object"], "tier": 0]] }

    func call(_ name: String, args: JSONValue) async throws -> JSONValue {
        switch name {
        case "echo_back": return ["echo": args]
        case "slow_one":
            try await Task.sleep(nanoseconds: 300_000_000)
            return "slow"
        default: throw ToolFailure("this Mac has no tool '\(name)'")
        }
    }
}

@Suite("Device client")
struct DeviceClientTests {
    static let url = URL(string: "wss://ira.example.com/v1/devices/ws")!

    func client(_ channel: FakeChannel, states: EventLog<DeviceState>, silence: Double = 5) -> (DeviceClient, FakeConnector) {
        var timing = DeviceClient.Timing()
        timing.silence = silence
        timing.ping = 30
        timing.jitter = false
        let connector = FakeConnector(channel: channel)
        let client = DeviceClient(
            url: DeviceClientTests.url, token: { "irad_test" }, tools: ScriptedTools(), label: "Studio Mac",
            connector: connector, timing: timing, log: IraLog(directory: nil), onState: { states.add($0) })
        return (client, connector)
    }

    @Test func helloWelcomeCallResultPingPong() async throws {
        let channel = FakeChannel()
        let states = EventLog<DeviceState>()
        let (client, connector) = client(channel, states: states)
        let run = Task { await client.runOnce(token: "irad_test") }

        #expect(await channel.waitFor { $0.count == 1 })
        let hello = try #require(channel.sentJSON.first)
        #expect(hello["type"] == "hello")
        #expect(hello["kind"] == "mac")
        #expect(connector.seen.lastHeaders["Authorization"] == "Bearer irad_test")
        #expect(connector.seen.lastHeaders["User-Agent"] == IraApp.userAgent)
        #expect(connector.seen.lastURL == DeviceClientTests.url)

        channel.push(["type": "welcome", "deviceId": 3, "label": "Studio Mac", "skills": ["files"]])
        #expect(await states.waitFor { $0.contains(.connected(deviceID: 3, skills: ["files"])) })

        channel.push(["type": "call", "id": "c1", "tool": "echo_back", "args": ["x": 1]])
        channel.push("this is not json")  // ignored; the connection goes on
        channel.push(["type": "call", "id": "c2", "tool": "no_such_tool", "args": [:]])
        channel.push(["type": "ping"])
        channel.push(["type": "skills", "skills": ["files", "screen"]])

        #expect(await channel.waitFor { sent in
            sent.contains(["type": "result", "id": "c1", "ok": true, "content": ["echo": ["x": 1]]])
                && sent.contains(["type": "result", "id": "c2", "ok": false, "error": "this Mac has no tool 'no_such_tool'"])
                && sent.contains(["type": "pong"])
        })
        #expect(await states.waitFor { $0.contains(.connected(deviceID: 3, skills: ["files", "screen"])) })

        channel.close(code: 4000)
        let closed = await run.value
        #expect(closed?.code == 4000)
    }

    @Test func callsRunSideBySide() async throws {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>())
        let run = Task { await client.runOnce(token: "irad_test") }
        #expect(await channel.waitFor { $0.count == 1 })
        channel.push(["type": "welcome", "deviceId": 1, "skills": []])
        channel.push(["type": "call", "id": "slow", "tool": "slow_one", "args": [:]])
        channel.push(["type": "call", "id": "fast", "tool": "echo_back", "args": [:]])
        #expect(await channel.waitFor { sent in sent.contains { $0["id"] == "slow" } })
        let ids = channel.sentJSON.compactMap { $0["id"]?.stringValue }
        #expect(ids == ["fast", "slow"])  // the fast answer did not wait for the slow one
        channel.close(code: 1000)
        _ = await run.value
    }

    @Test func aRefusedHelloEndsTheConnection() async {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>())
        let run = Task { await client.runOnce(token: "irad_test") }
        #expect(await channel.waitFor { $0.count == 1 })
        channel.push(["type": "error", "error": "this device was paired as 'android', not 'mac'"])
        let closed = await run.value
        #expect(closed?.code == 4400)
    }

    @Test func silenceDropsTheConnection() async {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>(), silence: 0.2)
        let run = Task { await client.runOnce(token: "irad_test") }
        #expect(await channel.waitFor { $0.count == 1 })
        channel.push(["type": "welcome", "deviceId": 1, "skills": []])
        let closed = await run.value
        #expect(closed?.reason == "the server went quiet")
        #expect(channel.closedWith != nil)
    }

    @Test func aRevokedTokenIsUnauthorized() async {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>())
        let run = Task { await client.runOnce(token: "irad_test") }
        #expect(await channel.waitFor { $0.count == 1 })
        channel.push(["type": "welcome", "deviceId": 1, "skills": []])
        channel.close(code: 4403)
        let closed = await run.value
        #expect(closed?.unauthorized == true)
        #expect(WebSocketClosed(httpStatus: 403).unauthorized)
        #expect(!WebSocketClosed(code: 4000).unauthorized)
    }

    @Test func goodbyeIsSentInsteadOfAHello() async {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>())
        channel.onSend = { _ in channel.close(code: 1000) }
        let said = await client.sayGoodbye()
        #expect(said)
        #expect(channel.sentJSON == [["type": "bye"]])
    }

    @Test func reconnectsAfterAFailedConnect() async {
        let states = EventLog<DeviceState>()
        var timing = DeviceClient.Timing()
        timing.backoff = [0.05]
        timing.jitter = false
        let connector = FakeConnector(channel: nil, error: WebSocketClosed(reason: "connection refused"))
        let client = DeviceClient(
            url: DeviceClientTests.url, token: { "irad_test" }, tools: ScriptedTools(), label: "Mac",
            connector: connector, timing: timing, log: IraLog(directory: nil), onState: { states.add($0) })
        client.start()
        #expect(await states.waitFor { $0.filter { $0 == .connecting }.count >= 3 })
        client.stop()
        #expect(states.all.contains(.waiting(seconds: 0.05, reason: "connection refused")))
    }
}

@Suite("Device events")
struct DeviceEventTests {
    @Test func eventsWaitForTheConnectionAndKeepTheirPace() async throws {
        let channel = FakeChannel()
        var timing = DeviceClient.Timing()
        timing.eventSpacing = 0.3
        timing.silence = 5
        let client = DeviceClient(
            url: URL(string: "wss://ira.example.com/v1/devices/ws")!, token: { "irad_test" }, tools: ScriptedTools(),
            label: "Mac", connector: FakeConnector(channel: channel), timing: timing, log: IraLog(directory: nil))
        client.announce(event: "task_done", title: "Task t1 is done", text: "2 files changed.", data: ["id": "t1"])
        client.announce(event: "task_failed", title: "Task t2 failed", text: "tests failed.")
        let run = Task { await client.runOnce(token: "irad_test") }
        #expect(await channel.waitFor { $0.count == 1 })
        channel.push(["type": "welcome", "deviceId": 1, "skills": ["tasks"]])
        #expect(await channel.waitFor { sent in sent.contains { $0["event"] == "task_done" } })
        let first = Date()
        #expect(await channel.waitFor { sent in sent.contains { $0["event"] == "task_failed" } })
        #expect(Date().timeIntervalSince(first) >= 0.2)
        let done = try #require(channel.sentJSON.first { $0["event"] == "task_done" })
        #expect(done == ["type": "event", "event": "task_done", "title": "Task t1 is done", "text": "2 files changed.", "data": ["id": "t1"]])
        channel.close(code: 1000)
        _ = await run.value
    }
}
