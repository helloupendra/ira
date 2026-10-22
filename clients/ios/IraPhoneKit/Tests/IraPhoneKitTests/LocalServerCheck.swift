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
    @Test(.timeLimit(.minutes(2)))
    func pairOfferTheToolsAskApproveAndTalkLive() async throws {
        let server = try #require(LocalServer.server)
        let token = try await pair(server)
        let calls = EventLog<String>()
        let device = try await connectDevice(server, token: token, calls: calls)
        defer { device.stop() }
        let client = AskClient(server: server, token: { token })
        let conversation = ConversationID.make()
        try await askWithADeviceTool(client, conversation: conversation, calls: calls)
        try await approveATier2Proposal(client, conversation: conversation, calls: calls)
        try await talkLive(server, token: token, client: client, conversation: conversation)
    }

    /// 1. Pairing, exactly as the app does it, and the Keychain rules.
    func pair(_ server: String) async throws -> String {
        let code = try #require(LocalServer.pairing)
        let paired = try await Pairing.exchange(server: server, code: code)
        #expect(paired.token.hasPrefix("irad_"))
        let record = PairingRecord(settings: freshSettings(), secrets: MemorySecretStore())
        try record.adopt(paired)
        return try #require(record.token)
    }

    /// 2. The device WebSocket: hello with the iPhone's tools, then welcome.
    func connectDevice(_ server: String, token: String, calls: EventLog<String>) async throws -> DeviceClient {
        let states = EventLog<DeviceState>()
        let url = try #require(Pairing.websocketURL(server: server))
        let device = DeviceClient(
            url: url, token: { token }, tools: CannedPhone(calls: calls), label: "Test iPhone",
            onState: { states.add($0) })
        device.start()
        let connected = await states.waitFor { $0.contains(where: LocalServer.isConnected) }
        #expect(connected)
        let skills = LocalServer.skills(states.all)
        #expect(skills.contains("contacts"))
        #expect(skills.contains("calls"))
        return device
    }

    /// 3. Ira calls a tool on this iPhone while answering a typed question.
    func askWithADeviceTool(_ client: AskClient, conversation: String, calls: EventLog<String>) async throws {
        var names: [String] = []
        var answer = ""
        for try await event in client.askStream("contacts lookup query=Rahul", conversationID: conversation) {
            switch event {
            case .tool(_, let name): names.append(name)
            case .done(let text, _, _): answer = text
            default: break
            }
        }
        #expect(names == ["contacts_lookup"])
        #expect(calls.all.contains("contacts_lookup"))
        #expect(answer.contains("Rahul Sharma"))
    }

    /// 4. A Tier 2 proposal on this iPhone: read back, then run on the person's yes.
    func approveATier2Proposal(_ client: AskClient, conversation: String, calls: EventLog<String>) async throws {
        var proposal: ActionCard?
        for try await event in client.askStream("call place number=9810000000", conversationID: conversation) {
            if case .action(let card) = event { proposal = card }
        }
        let card = try #require(proposal)
        #expect(card.tier == 2)
        #expect(card.need == .yes)
        let outcome = try await client.approve(actionID: card.id)
        #expect(outcome.status == "executed")
        #expect(calls.all.contains("call_place"))
    }

    /// 5. A live call with the device token: typed, spoken, a report, a barge-in.
    func talkLive(_ server: String, token: String, client: AskClient, conversation: String) async throws {
        let live = try LiveVoiceTransport(server: server, token: token)
        let heard = EventLog<TalkEvent>()
        try await live.start(conversationID: conversation) { heard.add($0) }
        defer { live.close() }

        live.text("hello Ira")
        #expect(await heard.waitFor { LocalServer.count(.done, in: $0) >= 1 })
        #expect(heard.all.contains(where: { LocalServer.heard($0) == "hello Ira" }))
        let messageID = try #require(heard.all.compactMap(LocalServer.messageID).first)

        // Report that answer, as the app's Report button does; someone else's is refused.
        try await client.report(messageID: messageID, reason: .wrong, note: "a check from the iPhone tests")
        await #expect(throws: AskClient.Failure.self) {
            try await client.report(messageID: 999_999, reason: .other, note: nil)
        }

        // A spoken turn, the voice detector's way: a second of a tone, then the hangover.
        var vad = EnergyVAD()
        let frames: [[Float]] = Array(repeating: Synth.tone(0.3), count: 50) + Array(repeating: Synth.silence(), count: 35)
        var at: Double = 10_000
        for frame in frames {
            for output in vad.process(frame, at: at) {
                switch output {
                case .speechStart(let start): live.speechStart(at: start)
                case .audio(let pcm): live.audio(pcm)
                case .speechEnd(let end): live.speechEnd(at: end)
                }
            }
            at += 20
        }
        #expect(await heard.waitFor { LocalServer.count(.done, in: $0) >= 2 })
        #expect(LocalServer.count(.heard, in: heard.all) >= 2)

        // A barge-in: speak while the next answer is on its way.
        live.text("tell me more")
        #expect(await heard.waitFor { LocalServer.count(.heard, in: $0) >= 3 })
        live.speechStart(at: 20_000)
        live.audio(PCM.int16Data(Synth.tone(0.3)))
        live.speechEnd(at: 20_020)
        #expect(await heard.waitFor { LocalServer.count(.interrupted, in: $0) >= 1 || LocalServer.count(.done, in: $0) >= 3 })
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

    static func isConnected(_ state: DeviceState) -> Bool {
        if case .connected = state { return true }
        return false
    }

    static func skills(_ states: [DeviceState]) -> [String] {
        for state in states.reversed() {
            if case .connected(_, let skills) = state { return skills }
        }
        return []
    }

    enum Kind { case heard, done, interrupted }

    static func count(_ kind: Kind, in events: [TalkEvent]) -> Int {
        var count = 0
        for event in events {
            switch (kind, event) {
            case (.heard, .heard), (.done, .done), (.interrupted, .interrupted): count += 1
            default: break
            }
        }
        return count
    }

    static func heard(_ event: TalkEvent) -> String? {
        if case .heard(_, let text) = event { return text }
        return nil
    }

    static func messageID(_ event: TalkEvent) -> Int? {
        if case .done(_, _, let id) = event { return id }
        return nil
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
            let phone: JSONValue = ["label": "mobile", "number": "+91 98100 00000"]
            let person: JSONValue = ["name": "Rahul Sharma", "phones": [phone]]
            return ["contacts": [person], "count": 1, "summary": "Rahul Sharma, +91 98100 00000."]
        case "call_place":
            return ["number": args["number"] ?? .null, "summary": "The iPhone is asking to call that number."]
        default:
            throw ToolFailure("not in this test")
        }
    }
}
