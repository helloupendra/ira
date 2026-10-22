import Foundation
import Testing
@testable import IraPhoneKit

@Suite("Streamed answers")
struct StreamParsingTests {
    @Test func serverSentEvents() {
        var parser = SSEParser()
        #expect(parser.line(#"data: {"type":"start","conversation_id":"c1"}"#) == [])
        #expect(parser.line("") == [["type": "start", "conversation_id": "c1"]])
        #expect(parser.line(": keepalive") == [])
        // URLSession's lines drop blank ones: a new data line ends the event before it.
        #expect(parser.line(#"data: {"type":"delta","text":"Hi"}"#) == [])
        #expect(parser.line(#"data: {"type":"done","text":"Hi"}"#) == [["type": "delta", "text": "Hi"]])
        #expect(parser.finish() == [["type": "done", "text": "Hi"]])
        #expect(parser.line("data: not json") == [])
        #expect(parser.finish() == [])
    }

    @Test func everyEventType() {
        #expect(AskEvent(["type": "start", "conversation_id": "ios-1"]) == .start(conversationID: "ios-1"))
        #expect(AskEvent(["type": "tool", "id": "t1", "name": "calendar_read", "arguments": [:]]) == .tool(id: "t1", name: "calendar_read"))
        #expect(AskEvent(["type": "tool_result", "id": "t1", "name": "calendar_read", "ok": true, "result": "{}", "truncated": false])
            == .toolResult(id: "t1", name: "calendar_read", ok: true))
        #expect(AskEvent(["type": "delta", "text": "Kal"]) == .delta("Kal"))
        #expect(AskEvent(["type": "error", "message": "no model could answer"]) == .error("no model could answer"))
        #expect(AskEvent(["type": "done", "text": "Kal free.", "model": "demo", "conversation_id": "ios-1", "message_id": 44])
            == .done(text: "Kal free.", conversationID: "ios-1", messageID: 44))
        #expect(AskEvent(["type": "later"]) == .other("later"))
        let action = AskEvent(["type": "action", "action": ["id": "act_9", "tool": "call_place", "summary": "Call Rahul Sharma, +91 98100 00000",
                                                           "status": "pending", "expires_in": 120, "tier": 2, "can_approve": true,
                                                           "confirm_roles": ["owner"], "can_confirm": true]])
        guard case .action(let card) = action else {
            Issue.record("expected an action")
            return
        }
        #expect(card.id == "act_9" && card.tier == 2 && card.need == .yes)
        #expect(card.statusWords == "Waiting for your yes")
    }

    @Test func serverInfoAndTheTalkMode() {
        let live = ServerInfo(["name": "Asha", "live": true, "tts": "polly", "stt": "transcribe", "mic_language": "hi-IN",
                               "permissions": ["actions", "ask", "voice"]])
        #expect(live.name == "Asha" && live.canAsk && live.speaks && live.micLanguage == "hi-IN")
        #expect(TalkMode.choose(live) == .live)
        let plain = ServerInfo(["name": "", "live": false, "tts": nil, "permissions": ["ask"]])
        #expect(plain.name == "Ira")
        #expect(TalkMode.choose(plain) == .phone(serverVoice: false))
        #expect(TalkMode.phone(serverVoice: false).explanation.contains("iPhone's voice"))
        #expect(TalkMode.choose(ServerInfo(["live": false, "tts": "polly", "permissions": ["ask", "voice"]])) == .phone(serverVoice: true))
    }
}

@Suite("Proposed actions")
struct ActionTests {
    @Test func whatACardAsksFor() {
        #expect(ActionCard(id: "a", tool: "t", summary: "s", tier: 2, canApprove: true, canConfirm: false).need == .yes)
        #expect(ActionCard(id: "a", tool: "t", summary: "s", tier: 3, canApprove: false, canConfirm: true).need == .pin)
        if case .cannot = ActionCard(id: "a", tool: "t", summary: "s", tier: 3, canApprove: false, canConfirm: false).need {} else {
            Issue.record("a role that cannot confirm gets no PIN box")
        }
        if case .cannot = ActionCard(id: "a", tool: "t", summary: "s", tier: 2, canApprove: false, canConfirm: true).need {} else {
            Issue.record("only the person who asked may say yes")
        }
        #expect(ActionCard(id: "a", tool: "t", summary: "s", status: "executed", tier: 2, canApprove: true, canConfirm: true).need == .settled)
        #expect(ActionCard(["summary": "no id"]) == nil)
    }

    @Test func outcomesInPlainWords() {
        #expect(ActionOutcome(["status": "executed", "message": "ok"]).sentence == "Done.")
        #expect(ActionOutcome(["status": "wrong_pin", "attempts_left": 2]).sentence == "That PIN is not right. 2 tries left before actions lock.")
        #expect(ActionOutcome(["status": "wrong_pin", "attempts_left": 1]).cardStatus == nil)
        #expect(ActionOutcome(["status": "locked", "locked_seconds": 600]).sentence == "Too many wrong PINs: actions are locked for 10 more minutes.")
        #expect(ActionOutcome(["status": "expired"]).sentence.contains("Ask Ira again"))
        #expect(ActionOutcome(["status": "no_pin"]).sentence.contains("Set one"))
        #expect(ActionOutcome(["status": "failed", "message": "the calendar is read-only"]).sentence.contains("read-only"))
        #expect(ActionOutcome(["status": "cancelled"]).cardStatus == "cancelled")
    }
}

/// The HTTP API against a URLProtocol stub: no network.
@Suite("Asking", .serialized)
struct AskClientTests {
    static func stream(_ lines: [String]) -> Data {
        Data(lines.map { "data: \($0)\n\n" }.joined().utf8)
    }

    @Test func askStreamSendsTheConversationAndTheDeviceKey() async throws {
        let host = "ask1.example.com"
        let session = StubProtocol.session(host: host) { request, _ in
            #expect(request.url?.path == "/v1/ask/stream")
            return .init(status: 200, body: AskClientTests.stream([
                #"{"type": "start", "conversation_id": "ios-abc"}"#,
                #"{"type": "tool", "id": "t1", "name": "calendar_read", "arguments": {}}"#,
                #"{"type": "tool_result", "id": "t1", "name": "calendar_read", "ok": true, "result": "{}", "truncated": false}"#,
                #"{"type": "delta", "text": "Kal 10 baje "}"#,
                #"{"type": "delta", "text": "meeting hai."}"#,
                #"{"type": "done", "text": "Kal 10 baje meeting hai.", "model": "demo", "conversation_id": "ios-abc", "message_id": 12}"#,
            ]), headers: ["Content-Type": "text/event-stream"])
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        var events: [AskEvent] = []
        for try await event in client.askStream("kal ka schedule?", conversationID: "ios-abc") { events.append(event) }
        #expect(events == [
            .start(conversationID: "ios-abc"), .tool(id: "t1", name: "calendar_read"),
            .toolResult(id: "t1", name: "calendar_read", ok: true), .delta("Kal 10 baje "), .delta("meeting hai."),
            .done(text: "Kal 10 baje meeting hai.", conversationID: "ios-abc", messageID: 12),
        ])
        let (request, body) = try #require(StubProtocol.requests(host).first)
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer irad_test")
        #expect(request.value(forHTTPHeaderField: "User-Agent") == IraPhone.userAgent)
        #expect(body.flatMap(JSONValue.parse) == ["text": "kal ka schedule?", "conversation_id": "ios-abc"])
    }

    @Test func aRemovedIPhoneIsSignedOut() async {
        let host = "ask2.example.com"
        let session = StubProtocol.session(host: host) { _, _ in
            .init(status: 401, body: Data(#"{"detail": "invalid or revoked token"}"#.utf8))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_old" })
        do {
            for try await _ in client.askStream("hi", conversationID: nil) {}
            Issue.record("expected a failure")
        } catch let failure as AskClient.Failure {
            #expect(failure.signedOut)
            #expect(failure.message == "invalid or revoked token")
        } catch {
            Issue.record("unexpected \(error)")
        }
    }

    @Test func askWholeForSiri() async throws {
        let host = "ask3.example.com"
        let session = StubProtocol.session(host: host) { _, _ in
            .init(status: 200, body: Data(#"""
                {"text": "Call Rahul Sharma?", "conversation_id": "ios-s", "message_id": 3,
                 "action": {"id": "act_2", "tool": "call_place", "summary": "Call Rahul Sharma, +91 98100 00000",
                            "status": "pending", "expires_in": 120, "tier": 2, "can_approve": true, "can_confirm": true,
                            "confirm_roles": ["owner"]}}
                """#.utf8))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        let answer = try await client.ask("Rahul ko call karo", conversationID: "ios-s")
        #expect(answer.text == "Call Rahul Sharma?")
        #expect(answer.messageID == 3)
        #expect(answer.action?.need == .yes)
    }

    @Test func approveConfirmCancelAndReport() async throws {
        let host = "ask4.example.com"
        let session = StubProtocol.session(host: host) { request, body in
            switch request.url?.path {
            case "/v1/actions/act_1/approve":
                return .init(status: 200, body: Data(#"{"status": "executed", "message": "Done"}"#.utf8))
            case "/v1/actions/act_1/confirm":
                #expect(body.flatMap(JSONValue.parse) == ["pin": "4321"])
                return .init(status: 403, body: Data(#"{"status": "wrong_pin", "message": "Wrong PIN", "attempts_left": 2}"#.utf8))
            case "/v1/actions/act_1/cancel":
                return .init(status: 200, body: Data(#"{"status": "cancelled", "message": "Cancelled"}"#.utf8))
            case "/v1/me/reports" where body.flatMap(JSONValue.parse)?["message_id"] == 12:
                #expect(body.flatMap(JSONValue.parse) == ["message_id": 12, "reason": "wrong", "note": "the time is wrong"])
                return .init(status: 200, body: Data(#"{"id": "r1", "status": "open"}"#.utf8))
            default:
                return .init(status: 404, body: Data(#"{"detail": "no such answer"}"#.utf8))
            }
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        #expect(try await client.approve(actionID: "act_1").status == "executed")
        let wrong = try await client.confirm(actionID: "act_1", pin: "4321")
        #expect(wrong.status == "wrong_pin" && wrong.attemptsLeft == 2)
        #expect(try await client.cancel(actionID: "act_1").cardStatus == "cancelled")
        try await client.report(messageID: 12, reason: .wrong, note: "  the time is wrong ")
        await #expect(throws: AskClient.Failure("That answer is no longer on your Ira, so it cannot be reported.", status: 404)) {
            try await client.report(messageID: 999, reason: .other, note: nil)
        }
    }

    @Test func answersSpokenInOrderByTheServersVoice() async throws {
        let host = "ask5.example.com"
        let session = StubProtocol.session(host: host) { request, body in
            switch request.url?.path {
            case "/v1/ask/stream":
                return .init(status: 200, body: AskClientTests.stream([
                    #"{"type": "start", "conversation_id": "ios-v"}"#,
                    #"{"type": "delta", "text": "Your calendar is free tomorrow. "}"#,
                    #"{"type": "delta", "text": "Shall I add the dentist?"}"#,
                    #"{"type": "done", "text": "Your calendar is free tomorrow. Shall I add the dentist?", "conversation_id": "ios-v", "message_id": 5}"#,
                ]))
            case "/v1/voice/speak":
                let text = body.flatMap(JSONValue.parse)?["text"]?.stringValue ?? ""
                return .init(status: 200, body: Data("MP3:\(text)".utf8), headers: ["Content-Type": "audio/mpeg"])
            default:
                return .init(status: 404, body: Data())
            }
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        let asking = AskSession(client: client, serverSpeaks: true)
        let events = EventLog<TalkEvent>()
        asking.ask("kal free hoon?", conversationID: "ios-v", spoken: true) { events.add($0) }
        #expect(await events.waitFor { $0.contains { if case .done = $0 { return true } else { return false } } })
        #expect(await events.waitFor { $0.filter { if case .audio = $0 { return true } else { return false } }.count == 2 })
        let spoken = events.all.compactMap { event -> String? in
            if case .audio(1, _, _, let data) = event { return String(decoding: data, as: UTF8.self) }
            return nil
        }
        #expect(spoken == ["MP3:Your calendar is free tomorrow.", "MP3:Shall I add the dentist?"])
        #expect(events.all.contains(.ready(conversationID: "ios-v", assistant: nil)))
        #expect(events.all.contains(.done(turn: 1, text: "Your calendar is free tomorrow. Shall I add the dentist?", messageID: 5)))
    }

    @Test func withoutAServerVoiceTheIPhoneSaysIt() async throws {
        let host = "ask6.example.com"
        let session = StubProtocol.session(host: host) { _, _ in
            .init(status: 200, body: AskClientTests.stream([
                #"{"type": "delta", "text": "Theek hai, kal 9 baje. "}"#,
                #"{"type": "done", "text": "Theek hai, kal 9 baje. Reminder added.", "conversation_id": "c"}"#,
            ]))
        }
        let client = AskClient(server: "https://\(host)", session: session, token: { "irad_test" })
        let asking = AskSession(client: client, serverSpeaks: false)
        let events = EventLog<TalkEvent>()
        asking.ask("yaad dilana", conversationID: nil, spoken: true) { events.add($0) }
        #expect(await events.waitFor { $0.filter { if case .say = $0 { return true } else { return false } }.count == 2 })
        let said = events.all.compactMap { event -> String? in
            if case .say(_, let seq, let text) = event { return "\(seq):\(text)" }
            return nil
        }
        #expect(said == ["0:Theek hai, kal 9 baje.", "1:Reminder added."])
        #expect(StubProtocol.requests(host).allSatisfy { $0.0.url?.path != "/v1/voice/speak" })
    }

    @Test func typedQuestionsAreNotSpoken() async throws {
        let host = "ask7.example.com"
        let session = StubProtocol.session(host: host) { _, _ in
            .init(status: 200, body: AskClientTests.stream([
                #"{"type": "delta", "text": "Hello there, how can I help? "}"#,
                #"{"type": "done", "text": "Hello there, how can I help?", "conversation_id": "c"}"#,
            ]))
        }
        let asking = AskSession(client: AskClient(server: "https://\(host)", session: session, token: { "irad_test" }), serverSpeaks: true)
        let events = EventLog<TalkEvent>()
        asking.ask("hello", conversationID: nil, spoken: false) { events.add($0) }
        #expect(await events.waitFor { $0.contains { if case .done = $0 { return true } else { return false } } })
        #expect(!events.all.contains { if case .audio = $0 { return true } else if case .say = $0 { return true } else { return false } })
    }
}
