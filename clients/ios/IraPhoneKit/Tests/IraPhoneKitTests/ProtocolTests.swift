import Foundation
import Testing
@testable import IraPhoneKit

@Suite("Device frames")
struct DeviceFrameTests {
    @Test func welcome() throws {
        let frame = try DeviceProtocol.decode(
            #"{"type":"welcome","deviceId":3,"label":"My iPhone","skills":["contacts"],"assistant":"Ira","wakePhrase":"Hey Ira"}"#)
        #expect(frame == .welcome(deviceID: 3, label: "My iPhone", skills: ["contacts"], assistant: "Ira", wakePhrase: "Hey Ira"))
    }

    @Test func call() throws {
        let frame = try DeviceProtocol.decode(#"{"type":"call","id":"9b0c","tool":"contacts_lookup","args":{"query":"Rahul"}}"#)
        #expect(frame == .call(id: "9b0c", tool: "contacts_lookup", args: ["query": "Rahul"]))
        let bare = try DeviceProtocol.decode(#"{"type":"call","id":"1","tool":"location_now","args":null}"#)
        #expect(bare == .call(id: "1", tool: "location_now", args: .object([:])))
    }

    @Test func pingPongSkillsErrorAndUnknown() throws {
        #expect(try DeviceProtocol.decode(#"{"type":"ping"}"#) == .ping)
        #expect(try DeviceProtocol.decode(#"{"type":"pong"}"#) == .pong)
        #expect(try DeviceProtocol.decode(#"{"type":"skills","skills":["contacts","calls"]}"#) == .skills(["contacts", "calls"]))
        #expect(try DeviceProtocol.decode(#"{"type":"error","error":"bad hello"}"#) == .error("bad hello"))
        #expect(try DeviceProtocol.decode(#"{"type":"event","event":"task_done","title":"x"}"#) == .other("event"))
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

    @Test func helloSaysItIsAnIPhoneWithItsTools() {
        let hello = DeviceProtocol.hello(label: "My iPhone", tools: ToolCatalog.definitions)
        #expect(hello["type"] == "hello")
        #expect(hello["kind"] == "ios")
        #expect(hello["label"] == "My iPhone")
        #expect(hello["version"]?.stringValue == IraPhone.version)
        #expect(hello["tools"]?.arrayValue?.count == ToolCatalog.all.count)
    }

    @Test func resultsFailuresAndTheSizeLimit() throws {
        #expect(DeviceProtocol.result(id: "1", content: ["summary": "ok"]) == ["type": "result", "id": "1", "ok": true, "content": ["summary": "ok"]])
        let failure = DeviceProtocol.failure(id: "1", error: String(repeating: "e", count: 400))
        #expect(failure["ok"] == false)
        #expect(failure["error"]?.stringValue?.count == 300)
        let huge = DeviceProtocol.result(id: "7", content: .string(String(repeating: "a", count: 1024 * 1024)))
        let sent = try #require(JSONValue.parse(DeviceProtocol.encodeResult(huge)))
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
        default: throw ToolFailure("this iPhone has no tool called \(name)")
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
            url: DeviceClientTests.url, token: { "irad_test" }, tools: ScriptedTools(), label: "My iPhone",
            connector: connector, timing: timing, onState: { states.add($0) })
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
        #expect(hello["kind"] == "ios")
        #expect(connector.seen.lastHeaders["Authorization"] == "Bearer irad_test")
        #expect(connector.seen.lastHeaders["User-Agent"] == "ira-ios/\(IraPhone.version)")
        #expect(connector.seen.lastURL == DeviceClientTests.url)

        channel.push(["type": "welcome", "deviceId": 3, "label": "My iPhone", "skills": ["contacts"]])
        #expect(await states.waitFor { $0.contains(.connected(deviceID: 3, skills: ["contacts"])) })

        channel.push(["type": "call", "id": "c1", "tool": "echo_back", "args": ["x": 1]])
        channel.push("this is not json")  // ignored; the connection goes on
        channel.push(["type": "call", "id": "c2", "tool": "no_such_tool", "args": [:]])
        channel.push(["type": "ping"])
        channel.push(["type": "skills", "skills": ["contacts", "calls"]])

        #expect(await channel.waitFor { sent in
            sent.contains(["type": "result", "id": "c1", "ok": true, "content": ["echo": ["x": 1]]])
                && sent.contains(["type": "result", "id": "c2", "ok": false, "error": "this iPhone has no tool called no_such_tool"])
                && sent.contains(["type": "pong"])
        })
        #expect(await states.waitFor { $0.contains(.connected(deviceID: 3, skills: ["contacts", "calls"])) })

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
        channel.push(["type": "error", "error": "this device was paired as 'mac', not 'ios'"])
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
        #expect(WebSocketClosed(httpStatus: 401).unauthorized)
        #expect(!WebSocketClosed(code: 4000).unauthorized)
        #expect(Plain.device(.refused)?.contains("Pair it again") == true)
    }

    @Test func goodbyeIsSentInsteadOfAHello() async {
        let channel = FakeChannel()
        let (client, _) = client(channel, states: EventLog<DeviceState>())
        channel.onSend = { _ in channel.close(code: 1000) }
        #expect(await client.sayGoodbye())
        #expect(channel.sentJSON == [["type": "bye"]])
    }

    @Test func reconnectsAfterAFailedConnectAndStops() async {
        let states = EventLog<DeviceState>()
        var timing = DeviceClient.Timing()
        timing.backoff = [0.05]
        timing.jitter = false
        let connector = FakeConnector(channel: nil, error: WebSocketClosed(reason: "the connection was refused"))
        let client = DeviceClient(
            url: DeviceClientTests.url, token: { "irad_test" }, tools: ScriptedTools(), label: "My iPhone",
            connector: connector, timing: timing, onState: { states.add($0) })
        client.start()
        #expect(client.isRunning)
        #expect(await states.waitFor { $0.filter { $0 == .connecting }.count >= 3 })
        client.stop()
        #expect(!client.isRunning)
        #expect(states.all.contains(.waiting(seconds: 0.05, reason: "the connection was refused")))
        #expect(states.all.last == .stopped)
    }

    @Test func anUnreadableKeyWaitsAndNeverUnpairs() async {
        let states = EventLog<DeviceState>()
        let client = DeviceClient(
            url: DeviceClientTests.url, token: { nil }, tools: ScriptedTools(), label: "My iPhone",
            connector: FakeConnector(channel: FakeChannel()), onState: { states.add($0) })
        client.start()
        #expect(await states.waitFor { $0.contains(.keyUnavailable) })
        client.stop()
        #expect(Plain.device(.keyUnavailable) == PairingRecord.unreadable)
    }
}

@Suite("Live voice")
struct LiveVoiceTests {
    func connect(_ channel: FakeChannel, readyTimeout: Double = 2) -> (LiveVoiceTransport, FakeConnector) {
        let connector = FakeConnector(channel: channel)
        let live = try! LiveVoiceTransport(
            server: "https://ira.example.com", token: "irad_test", connector: connector, readyTimeout: readyTimeout)
        return (live, connector)
    }

    @Test func aWholeTurnAsProtocol1Says() async throws {
        let channel = FakeChannel()
        let (live, connector) = connect(channel)
        let events = EventLog<TalkEvent>()
        channel.push(["type": "ready", "protocol": 1, "conversation_id": "ios-c9", "assistant": "Ira", "languages": ["en-IN", "hi-IN"], "tts": "polly"])
        try await live.start(conversationID: "ios-c9") { events.add($0) }

        #expect(connector.seen.lastURL?.absoluteString == "wss://ira.example.com/v1/voice/live")
        #expect(connector.seen.lastHeaders["Authorization"] == "Bearer irad_test")
        let start = try #require(channel.sentJSON.first)
        #expect(start == ["type": "start", "protocol": 1, "client": .string(IraPhone.userAgent), "conversation_id": "ios-c9"])
        #expect(events.all == [.ready(conversationID: "ios-c9", assistant: "Ira")])

        // The person speaks: speech_start, audio in binary frames of 100 ms at most, speech_end.
        live.speechStart(at: 1234.56)
        live.audio(Data(repeating: 1, count: 640 * 6))
        live.speechEnd(at: 2345.6)
        #expect(await channel.waitFor { $0.contains(["type": "speech_end", "at": 2345.6]) })
        #expect(channel.sentJSON.contains(["type": "speech_start", "at": 1234.6]))
        #expect(channel.sentData.map(\.count) == [3200, 640])

        // Ira answers.
        channel.push(["type": "partial", "text": "kal subah", "language": "hi-IN"])
        channel.push(["type": "heard", "turn": 1, "text": "kal subah 9 baje yaad dilana", "language": "hi-IN"])
        channel.push(["type": "delta", "turn": 1, "text": "Theek hai."])
        channel.push(["type": "audio", "turn": 1, "seq": 0, "text": "Theek hai.", "format": "mp3", "bytes": 3])
        channel.push(data: Data([0xFF, 0xFB, 0x90]))
        channel.push(["type": "action", "turn": 1, "action": ["id": "act_1", "tool": "reminders_add", "summary": "Remind you at 9:00", "tier": 2, "status": "pending", "can_approve": true]])
        channel.push(["type": "ping"])
        channel.push(["type": "done", "turn": 1, "text": "Theek hai.", "message_id": 812, "timings": ["stt_ms": 240]])
        #expect(await events.waitFor { $0.contains(.done(turn: 1, text: "Theek hai.", messageID: 812)) })
        #expect(events.all.contains(.partial("kal subah")))
        #expect(events.all.contains(.heard(turn: 1, text: "kal subah 9 baje yaad dilana")))
        #expect(events.all.contains(.delta(turn: 1, text: "Theek hai.")))
        #expect(events.all.contains(.audio(turn: 1, seq: 0, text: "Theek hai.", data: Data([0xFF, 0xFB, 0x90]))))
        #expect(events.all.contains { if case .action(1, let card) = $0 { return card.id == "act_1" && card.need == .yes } else { return false } })
        #expect(await channel.waitFor { $0.contains(["type": "pong"]) })

        live.played(turn: 1, at: 3012.04)
        live.text("aur kuch?")
        live.interrupt()
        #expect(await channel.waitFor { sent in
            sent.contains(["type": "played", "turn": 1, "at": 3012]) && sent.contains(["type": "text", "text": "aur kuch?"])
                && sent.contains(["type": "interrupt"])
        })

        channel.push(["type": "interrupted", "turn": 2])
        channel.push(["type": "error", "message": "transcription failed", "fatal": false])
        #expect(await events.waitFor { $0.contains(.error("transcription failed", fatal: false)) })
        #expect(events.all.contains(.interrupted(turn: 2)))

        live.close()
        #expect(await channel.waitFor { $0.contains(["type": "bye"]) })
    }

    @Test func aServerWithoutLiveVoice() async {
        let connector = FakeConnector(channel: nil, error: WebSocketClosed(httpStatus: 404, reason: "not found"))
        let live = try! LiveVoiceTransport(server: "https://ira.example.com", token: "irad_test", connector: connector)
        await #expect(throws: LiveUnavailable.self) { try await live.start(conversationID: nil) { _ in } }
    }

    @Test func aFatalErrorBeforeReady() async {
        let channel = FakeChannel()
        let (live, _) = connect(channel)
        channel.push(["type": "error", "message": "speech-to-text of type transcribe is needed", "fatal": true])
        await #expect(throws: LiveUnavailable("speech-to-text of type transcribe is needed")) {
            try await live.start(conversationID: nil) { _ in }
        }
        #expect(channel.closedWith != nil)
    }

    @Test func noAnswerInTime() async {
        let channel = FakeChannel()
        let (live, _) = connect(channel, readyTimeout: 0.2)
        await #expect(throws: LiveUnavailable.self) { try await live.start(conversationID: nil) { _ in } }
    }

    @Test func audioForAnInterruptedTurnIsDropped() async throws {
        let channel = FakeChannel()
        let (live, _) = connect(channel)
        let events = EventLog<TalkEvent>()
        channel.push(["type": "ready", "protocol": 1])
        try await live.start(conversationID: nil) { events.add($0) }
        channel.push(["type": "audio", "turn": 3, "seq": 1, "text": "x", "format": "mp3", "bytes": 1])
        channel.push(["type": "interrupted", "turn": 3])
        channel.push(data: Data([1]))  // a frame no audio message announced: ignored
        channel.push(["type": "done", "turn": 3, "text": ""])
        #expect(await events.waitFor { $0.contains(.done(turn: 3, text: "", messageID: nil)) })
        #expect(!events.all.contains { if case .audio = $0 { return true } else { return false } })
        live.close()
    }

    @Test func liveMessagesDecode() throws {
        #expect(try LiveProtocol.decode(#"{"type":"ready","protocol":1,"conversation_id":"c","assistant":"Ira","languages":["hi-IN"],"tts":"polly"}"#)
            == .ready(conversationID: "c", assistant: "Ira", languages: ["hi-IN"], tts: "polly"))
        #expect(try LiveProtocol.decode(#"{"type":"done","turn":2,"text":"ok","message_id":5}"#)
            == .done(turn: 2, text: "ok", messageID: 5, timings: nil))
        #expect(try LiveProtocol.decode(#"{"type":"error","message":"no","fatal":true}"#) == .error(message: "no", fatal: true))
        #expect(try LiveProtocol.decode(#"{"type":"later"}"#) == .other("later"))
        #expect(throws: LiveProtocol.BadMessage.self) { try LiveProtocol.decode("[]") }
        #expect(LiveProtocol.start(conversationID: nil) == ["type": "start", "protocol": 1, "client": .string(IraPhone.userAgent)])
    }
}
