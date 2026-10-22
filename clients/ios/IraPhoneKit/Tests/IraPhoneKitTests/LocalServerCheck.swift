import Foundation
import Testing
@testable import IraPhoneKit

/// An opt-in check against a running Ira (`ira serve` with the demo model and
/// `voice.stt.type: fake`, `voice.tts.type: fake`), skipped unless these are set:
///
///     IRA_TEST_SERVER=http://localhost:8799
///     IRA_TEST_PAIRING=ABCD-EFGH     an iPhone pairing code with the contacts and calls skills
///
/// `scripts/local-ira.sh` starts such a server and makes the code; CI runs this
/// on an iOS simulator. It pairs as the app does, offers the iPhone's tools,
/// answers a real tool call, says yes to a Tier 2 proposal, and holds a live
/// call: a typed turn, a spoken one, a barge-in, and a report.
@Suite("Against a local Ira", .serialized, .enabled(if: LocalServer.configured))
struct LocalServerCheck {
    @Test func pairOfferTheToolsAskApproveAndTalkLive() async throws {
        let server = try #require(LocalServer.server)
        let code = try #require(LocalServer.pairing)

        // 1. Pairing, exactly as the app does it.
        let paired = try await Pairing.exchange(server: server, code: code)
        #expect(paired.token.hasPrefix("irad_"))
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: freshSettings(), secrets: secrets)
        try record.adopt(paired)
        let token = try #require(record.token)

        // 2. The device WebSocket: hello with the iPhone's tools, then welcome.
        let calls = EventLog<String>()
        let states = EventLog<DeviceState>()
        let device = DeviceClient(
            url: try #require(Pairing.websocketURL(server: server)), token: { token }, tools: CannedPhone(calls: calls),
            label: "Test iPhone", onState: { states.add($0) })
        device.start()
        defer { device.stop() }
        #expect(await states.waitFor { $0.contains { if case .connected = $0 { return true } else { return false } } })
        guard case .connected(_, let skills)? = states.all.last(where: { if case .connected = $0 { return true } else { return false } })
        else { return }
        #expect(skills.contains("contacts") && skills.contains("calls"))

        // 3. Ira calls a tool on this iPhone while answering a typed question.
        let client = AskClient(server: server, token: { token })
        let conversation = ConversationID.make()
        var events: [AskEvent] = []
        for try await event in client.askStream("contacts lookup query=Rahul", conversationID: conversation) {
            events.append(event)
        }
        #expect(events.contains(.tool(id: events.compactMap { if case .tool(let id, _) = $0 { return id } else { return nil } }.first ?? "", name: "contacts_lookup")))
        #expect(calls.all.contains("contacts_lookup"))
        guard case .done(let text, _, _)? = events.last else {
            Issue.record("the stream did not end with done: \(events)")
            return
        }
        #expect(text.contains("Rahul Sharma"))

        // 4. A Tier 2 proposal on this iPhone: read back, then run on the person's yes.
        var proposal: ActionCard?
        for try await event in client.askStream("call place number=9810000000", conversationID: conversation) {
            if case .action(let card) = event { proposal = card }
        }
        let card = try #require(proposal)
        #expect(card.tier == 2 && card.need == .yes)
        let outcome = try await client.approve(actionID: card.id)
        #expect(outcome.status == "executed", "\(outcome)")
        #expect(calls.all.contains("call_place"))

        // 5. A live call with the device token.
        let live = try LiveVoiceTransport(server: server, token: token)
        let heard = EventLog<TalkEvent>()
        try await live.start(conversationID: conversation) { heard.add($0) }
        defer { live.close() }
        live.text("hello Ira")
        #expect(await heard.waitFor { $0.contains { if case .done = $0 { return true } else { return false } } })
        let messageID = heard.all.compactMap { if case .done(_, _, let id) = $0 { return id } else { return nil } }.first
        #expect(heard.all.contains { if case .heard(_, let said) = $0 { return said == "hello Ira" } else { return false } })

        // Report that answer, as the app's Report button does; someone else's is refused.
        try await client.report(messageID: try #require(messageID), reason: .wrong, note: "a check from the iPhone tests")
        await #expect(throws: AskClient.Failure.self) { try await client.report(messageID: 999_999, reason: .other, note: nil) }

        // A spoken turn: the voice detector's way, a second of a tone, then the hangover.
        var vad = EnergyVAD()
        let tone = (0..<50).map { index in (0..<320).map { 0.3 * sinf(2 * .pi * 220 * Float($0 + index * 320) / 16_000) } }
        let quiet = Array(repeating: [Float](repeating: 0, count: 320), count: 35)
        for (index, frame) in (tone + quiet).enumerated() {
            for output in vad.process(frame, at: 10_000 + Double(index) * 20) {
                switch output {
                case .speechStart(let at): live.speechStart(at: at)
                case .audio(let pcm): live.audio(pcm)
                case .speechEnd(let at): live.speechEnd(at: at)
                }
            }
        }
        #expect(await heard.waitFor { $0.filter { if case .done = $0 { return true } else { return false } }.count >= 2 })
        #expect(heard.all.filter { if case .heard = $0 { return true } else { return false } }.count >= 2)

        // A barge-in: speak while the next answer is on its way.
        live.text("tell me more")
        #expect(await heard.waitFor { $0.filter { if case .heard = $0 { return true } else { return false } }.count >= 3 })
        live.speechStart(at: 20_000)
        live.audio(PCM.int16Data(tone[0]))
        live.speechEnd(at: 20_020)
        #expect(await heard.waitFor { events in
            events.contains { if case .interrupted = $0 { return true } else { return false } }
                || events.filter { if case .done = $0 { return true } else { return false } }.count >= 3
        })
    }
}

enum LocalServer {
    static var server: String? { value("IRA_TEST_SERVER") }
    static var pairing: String? { value("IRA_TEST_PAIRING") }
    static var configured: Bool { server != nil && pairing != nil }

    static func value(_ name: String) -> String? {
        let text = ProcessInfo.processInfo.environment[name]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return text.isEmpty ? nil : text
    }
}

/// The iPhone's tools as the hello lists them, answered with canned results.
struct CannedPhone: ToolRunner {
    let calls: EventLog<String>
    var definitions: [JSONValue] { ToolCatalog.definitions }

    func call(_ name: String, args: JSONValue) async throws -> JSONValue {
        calls.add(name)
        switch name {
        case "contacts_lookup":
            return ["contacts": [["name": "Rahul Sharma", "phones": [["label": "mobile", "number": "+91 98100 00000"]]]],
                    "count": 1, "summary": "Rahul Sharma, +91 98100 00000."]
        case "call_place":
            return ["number": args["number"] ?? .null, "summary": "The iPhone is asking to call that number."]
        default:
            throw ToolFailure("not in this test")
        }
    }
}
