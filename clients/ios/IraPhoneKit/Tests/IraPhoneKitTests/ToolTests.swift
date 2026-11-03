import Foundation
import Testing
@testable import IraPhoneKit

@Suite("Tool catalog")
struct ToolCatalogTests {
    /// The server's rules for a hello (docs/devices.md), and the iPhone's skills
    /// as the server lists them for kind `ios`.
    @Test func everyToolFollowsTheServersRules() throws {
        let names = ToolCatalog.all.map(\.name)
        #expect(Set(names).count == names.count)
        #expect(names.count <= 30)
        for spec in ToolCatalog.all {
            #expect(spec.name.range(of: #"^[a-z][a-z0-9_]{2,40}$"#, options: .regularExpression) != nil, "\(spec.name)")
            let definition = spec.definition
            #expect(definition["skill"]?.stringValue == spec.skill.rawValue)
            #expect(definition["tier"]?.intValue == spec.tier)
            let description = try #require(definition["description"]?.stringValue)
            #expect(!description.isEmpty && description.count <= 1000)
            let parameters = try #require(definition["parameters"])
            #expect(parameters["type"] == "object")
            #expect(parameters["additionalProperties"] == false)
            #expect(parameters.encoded().utf8.count <= 8 * 1024)
            for required in parameters["required"]?.arrayValue ?? [] {
                #expect(parameters["properties"]?[required.stringValue ?? ""] != nil)
            }
        }
        #expect(Set(ToolCatalog.all.map(\.skill.rawValue)) == ["contacts", "calendar", "reminders", "location", "calls", "apps"])
    }

    @Test func tiersAreFixedHere() {
        let tiers = Dictionary(uniqueKeysWithValues: ToolCatalog.all.map { ($0.name, $0.tier) })
        #expect(tiers == [
            "contacts_lookup": 0,
            "calendar_read": 0, "calendar_add": 2,
            "reminders_list": 0, "reminders_add": 1, "reminders_done": 1,
            "location_now": 0,
            "call_place": 2,
            "app_open": 1, "url_open": 2,
        ])
    }

    @Test func nothingIOSForbidsIsOffered() {
        for name in ["calls_recent", "sms_read", "sms_send", "notifications_read", "messages_send", "screen_read"] {
            #expect(ToolCatalog.spec(name) == nil)
        }
    }

    @Test func everyDeadlineIsUnderTheServers25Seconds() {
        for spec in ToolCatalog.all { #expect(Toolbox.deadline(for: spec.name) < 25) }
    }
}

/// Permissions as a test wants them.
final class FakePermissions: PermissionProvider, @unchecked Sendable {
    private let lock = NSLock()
    private var states: [ChecklistItem: PermissionState]
    private var asked: [ChecklistItem] = []
    let answer: PermissionState

    init(_ states: [ChecklistItem: PermissionState], answer: PermissionState = .allowed) {
        self.states = states
        self.answer = answer
    }

    func state(_ item: ChecklistItem) -> PermissionState { lock.withLock { states[item] ?? .allowed } }

    func request(_ item: ChecklistItem) async -> PermissionState {
        lock.withLock {
            asked.append(item)
            states[item] = answer
            return answer
        }
    }

    var requests: [ChecklistItem] { lock.withLock { asked } }
}

@Suite("Toolbox")
struct ToolboxTests {
    func toolbox(
        _ permissions: FakePermissions, foreground: Bool = true, deadline: Double = 5, activity: EventLog<Activity>? = nil
    ) -> Toolbox {
        Toolbox(
            permissions: permissions, eventKit: EventKitTools(), opener: { _ in true }, foreground: { foreground },
            stand: { name, args in
                if name == "location_now" { try await Task.sleep(nanoseconds: 120_000_000_000) }
                return ["ran": .string(name), "args": args]
            },
            deadlines: { _ in deadline }, record: { activity?.add($0) })
    }

    @Test func anAllowedSkillRuns() async throws {
        let activity = EventLog<Activity>()
        let box = toolbox(FakePermissions([:]), activity: activity)
        let result = try await box.call("contacts_lookup", args: ["query": "Avery"])
        #expect(result["ran"] == "contacts_lookup")
        #expect(activity.all.map(\.tool) == ["contacts_lookup"] && activity.all.allSatisfy(\.ok))
        #expect(activity.all.first?.verb == "Looked up a contact")
    }

    @Test func notAskedYetAsksOnlyWhileOnScreen() async throws {
        let shown = FakePermissions([.skill(.calendar): .notAsked])
        _ = try await toolbox(shown).call("calendar_read", args: [:])
        #expect(shown.requests == [.skill(.calendar)])

        let hidden = FakePermissions([.skill(.calendar): .notAsked])
        await #expect(throws: ToolFailure("Ira has not asked for Calendar on the iPhone yet. Open Ira on the iPhone and allow Calendar on its checklist, then ask again")) {
            try await toolbox(hidden, foreground: false).call("calendar_read", args: [:])
        }
        #expect(hidden.requests.isEmpty)
    }

    @Test func aNoSaysWhereToSwitchItOn() async {
        let box = toolbox(FakePermissions([.skill(.reminders): .denied]))
        do {
            _ = try await box.call("reminders_list", args: [:])
            Issue.record("expected a refusal")
        } catch let failure as ToolFailure {
            #expect(failure.message.contains("Settings, Ira, Reminders"))
        } catch {
            Issue.record("unexpected \(error)")
        }
        let partial = toolbox(FakePermissions([.skill(.calendar): .partial("Ira may add events but not read them: choose Full Access.")]))
        await #expect(throws: ToolFailure.self) { try await partial.call("calendar_read", args: [:]) }
    }

    @Test func aStuckToolAnswersInTime() async {
        let activity = EventLog<Activity>()
        let box = toolbox(FakePermissions([:]), deadline: 0.2, activity: activity)
        let started = Date()
        await #expect(throws: ToolFailure.self) { try await box.call("location_now", args: [:]) }
        // The tool would take 120 s; a slow simulator still answers long before.
        #expect(Date().timeIntervalSince(started) < 60)
        #expect(activity.all.map(\.ok) == [false])
    }

    @Test func anUnknownToolIsRefused() async {
        await #expect(throws: ToolFailure("this iPhone has no tool called sms_read")) {
            try await toolbox(FakePermissions([:])).call("sms_read", args: [:])
        }
    }
}

@Suite("Calls")
struct CallToolTests {
    @Test func onlyDigitsAndALeadingPlus() throws {
        #expect(try CallTool.dialable("+91 00100-00000") == "+910010000000")
        #expect(try CallTool.dialable("(000) 4567 8901") == "00045678901")
        #expect(try CallTool.dialable("100") == "100")
        for bad in ["*21*0010000000#", "98100#", "call me", "9+1", "12", "+"] {
            #expect(throws: ToolFailure.self, "\(bad)") { try CallTool.dialable(bad) }
        }
        #expect(CallTool.telURL("+910010000000")?.absoluteString == "tel:+910010000000")
    }

    @Test func theIPhoneAsksAndThePersonTaps() async throws {
        let opened = EventLog<URL>()
        let result = try await CallTool.place(["number": "+91 00100 00000", "name": "Avery Stone"], foreground: true) { url in
            opened.add(url)
            return true
        }
        #expect(opened.all.map(\.absoluteString) == ["tel:+910010000000"])
        #expect(result["summary"]?.stringValue?.contains("taps Call") == true)
    }

    @Test func offScreenOrWithoutAPhoneItSaysWhy() async {
        await #expect(throws: ToolFailure.self) {
            try await CallTool.place(["number": "0010000000"], foreground: false) { _ in true }
        }
        await #expect(throws: ToolFailure("this iPhone cannot make calls (an iPad or a simulator?)")) {
            try await CallTool.place(["number": "0010000000"], foreground: true) { _ in false }
        }
        await #expect(throws: ToolFailure("unknown argument(s): text")) {
            try await CallTool.place(["number": "0010000000", "text": "hi"], foreground: true) { _ in true }
        }
    }
}

@Suite("Tool helpers")
struct ToolHelperTests {
    @Test func contactQueries() {
        #expect(ContactsTool.kind(of: "avery@example.com") == .email("avery@example.com"))
        #expect(ContactsTool.kind(of: "+91 00100 00000") == .number("910010000000"))
        #expect(ContactsTool.kind(of: "Avery Stone") == .name("Avery Stone"))
        #expect(ContactsTool.sameNumber("00100 00000", "+91 00100-00000"))
        #expect(ContactsTool.sameNumber("00000", "+91 00100 00000"))
        #expect(!ContactsTool.sameNumber("00100 00001", "+91 00100 00000"))
    }

    @Test func datesAsModelsWriteThem() throws {
        let zone = TimeZone(identifier: "Asia/Kolkata")!
        let day = try #require(LocalDate.parse("2026-10-23", timeZone: zone))
        #expect(!day.hasTime)
        let time = try #require(LocalDate.parse("2026-10-23T14:30", timeZone: zone))
        #expect(time.hasTime)
        #expect(LocalDate.iso(time.date, timeZone: zone) == "2026-10-23T14:30:00+05:30")
        #expect(LocalDate.parse("2026-02-30", timeZone: zone) == nil)
        #expect(LocalDate.parse("tomorrow", timeZone: zone) == nil)
    }

    @Test func locationInWords() {
        #expect(LocationTool.rounded(10.1234567) == 10.12346)
        #expect(LocationTool.summary(address: "14 Main Road", latitude: 0, longitude: 0, accuracy: 35)
            == "14 Main Road (within 35 m)")
        #expect(LocationTool.summary(address: nil, latitude: 10.12346, longitude: 20.98765, accuracy: 65)
            == "10.12346, 20.98765 (within 65 m)")
    }

    @Test func argumentsAreChecked() throws {
        #expect(throws: ToolFailure("unknown argument(s): x")) { try ToolArgs(["x": 1], allowed: ["query"]) }
        #expect(throws: ToolFailure("arguments must be an object")) { try ToolArgs("text", allowed: []) }
        let args = try ToolArgs(["query": "  Avery  ", "days": 99], allowed: ["query", "days"])
        #expect(try args.text("query") == "Avery")
        #expect(try args.number("days", 1...31) == 31)
    }
}
