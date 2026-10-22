import Foundation
import Security
import Testing
@testable import IraPhoneKit

func freshSettings() -> AppSettings {
    let name = "ira-tests-\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: name)!
    defaults.removePersistentDomain(forName: name)
    return AppSettings(defaults: defaults)
}

let deviceToken = "irad_" + String(repeating: "k", count: 43)

func paired(_ server: String = "https://ira.example.com") -> Pairing.Paired {
    Pairing.Paired(server: server, token: deviceToken, deviceID: 4, label: "My iPhone", skills: [], assistant: "Asha")
}

@Suite("Keychain rules")
struct KeychainRuleTests {
    @Test func pairedNeedsTheKeyAndTheServer() throws {
        let settings = freshSettings()
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: settings, secrets: secrets)
        #expect(record.status == .unpaired)
        try record.adopt(paired())
        #expect(record.status == .paired)
        #expect(record.token == deviceToken)
        #expect(settings.server == "https://ira.example.com")
        #expect(settings.deviceID == 4)
        #expect(settings.assistantName == "Asha")
    }

    @Test func aKeyThatCannotBeReadIsNeverNotPaired() throws {
        let settings = freshSettings()
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: settings, secrets: secrets)
        try record.adopt(paired())
        // The iPhone restarted and was not unlocked yet.
        secrets.fail(SecretAccount.device, status: errSecInteractionNotAllowed)
        #expect(record.status == .keyUnreadable(errSecInteractionNotAllowed))
        #expect(record.token == nil)
        #expect(secrets.deletions.isEmpty)
        #expect(settings.server == "https://ira.example.com")
        secrets.fail(SecretAccount.device, status: nil)
        #expect(record.status == .paired)
    }

    @Test func pairingAgainReplacesTheKeyWithoutDeletingIt() throws {
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: freshSettings(), secrets: secrets)
        try record.adopt(paired())
        try record.adopt(paired("https://other.example.com"))
        #expect(secrets.deletions.isEmpty)
        #expect(record.settings.server == "https://other.example.com")
    }

    @Test func onlyADeviceTokenIsKept() {
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: freshSettings(), secrets: secrets)
        let session = Pairing.Paired(server: "https://ira.example.com", token: "ira_s_" + String(repeating: "s", count: 40),
                                     deviceID: 1, label: "x", skills: [], assistant: nil)
        #expect(throws: SecretError.self) { try record.adopt(session) }
        #expect(secrets.load(SecretAccount.device) == nil)
        #expect(TokenShape.isDeviceToken(deviceToken))
        #expect(!TokenShape.isDeviceToken("irad_short"))
    }

    @Test func removingOnPurposeForgetsBoth() throws {
        let settings = freshSettings()
        let secrets = MemorySecretStore()
        let record = PairingRecord(settings: settings, secrets: secrets)
        try record.adopt(paired())
        record.removeOnPurpose()
        #expect(record.status == .unpaired)
        #expect(secrets.deletions == [SecretAccount.device])
        #expect(settings.server.isEmpty)
    }

    @Test func theItemIsThisDeviceOnlyAfterFirstUnlockAndNeverSynced() {
        let store = KeychainStore(service: "io.github.helloupendra.ira.tests")
        let add = store.addQuery("device", data: Data("x".utf8))
        #expect(add[kSecAttrAccessible as String] as? String == kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
        #expect((add[kSecAttrSynchronizable as String] as? Bool) == false)
        #expect(add[kSecAttrService as String] as? String == "io.github.helloupendra.ira.tests")
        #expect(add[kSecClass as String] as? String == kSecClassGenericPassword as String)
    }

    #if os(iOS)
    /// The real Keychain, on the simulator. A test process without the app's
    /// entitlements may be refused (-34018); that says nothing about the app.
    @Test func theRealKeychainKeepsAndForgets() throws {
        let store = KeychainStore(service: "io.github.helloupendra.ira.tests.\(UUID().uuidString)")
        do {
            try store.save(deviceToken, account: "device")
        } catch {
            if "\(error)".contains("-34018") { return }
            throw error
        }
        #expect(store.read("device") == .found(deviceToken))
        try store.save(deviceToken + "x", account: "device")
        #expect(store.read("device") == .found(deviceToken + "x"))
        #expect(store.delete("device"))
        #expect(store.read("device") == .missing)
    }
    #endif
}

@Suite("Settings")
struct SettingsTests {
    @Test func oneConversationUntilANewOne() {
        let settings = freshSettings()
        let first = settings.conversationID
        #expect(first.hasPrefix("ios-") && ConversationID.isValid(first))
        #expect(settings.conversationID == first)
        let second = settings.newConversation()
        #expect(second != first && settings.conversationID == second)
        settings.adoptConversation("not valid!")
        #expect(settings.conversationID == second)
        settings.adoptConversation("ios-server-made")
        #expect(settings.conversationID == "ios-server-made")
    }

    @Test func forgettingThePairingStartsSetupAgain() {
        let settings = freshSettings()
        settings.server = "https://ira.example.com"
        settings.setupDone = true
        settings.forgetPairing()
        #expect(settings.server.isEmpty)
        #expect(!settings.setupDone)
        #expect(settings.deviceLabel == "My iPhone")
    }

    @Test func theLogMasksKeysAndCodes() {
        let line = IraLog.redact("paired with irad_abcdefghijklmnopqrstuvwxyz and code=ABCD-EFGH, session ira_s_zzzzzzzz")
        #expect(!line.contains("irad_abc") && !line.contains("ABCD") && !line.contains("ira_s_zz"))
    }
}

@Suite("Get Ira ready")
struct ChecklistTests {
    @Test func eachRowSaysWhatToPress() {
        let rows = Checklist.rows(paired: false) { item in
            switch item {
            case .microphone: return .allowed
            case .speech: return .notAsked
            case .skill(.contacts): return .denied
            case .skill(.calendar): return .partial("Ira may add events but not read them: choose Full Access.")
            case .skill(.location): return .restricted
            default: return .notAsked
            }
        }
        func action(_ id: String) -> ChecklistRow.Action? { rows.first { $0.id == id }?.action }
        #expect(rows.map(\.id) == ["pair", "microphone", "speech", "contacts", "calendar", "reminders", "location", "calls"])
        #expect(action("pair") == .pair)
        #expect(action("microphone") == .done)
        #expect(action("speech") == .allow)
        if case .openSettings(let why) = action("contacts") { #expect(why.contains("will not ask again")) } else { Issue.record("contacts") }
        if case .openSettings(let why) = action("calendar") { #expect(why.contains("Full Access")) } else { Issue.record("calendar") }
        if case .unavailable = action("location") {} else { Issue.record("location") }
        #expect(rows.allSatisfy { !$0.reason.isEmpty })
        #expect(!Checklist.ready(rows))
    }

    @Test func readyNeedsPairingAndTheMicrophoneOnly() {
        let rows = Checklist.rows(paired: true) { item in item == .microphone ? .allowed : .denied }
        #expect(Checklist.ready(rows))
        let noMic = Checklist.rows(paired: true) { _ in .notAsked }
        #expect(!Checklist.ready(noMic))
    }

    @Test func busyWordsNameTheStep() {
        #expect(StepWords.tool("calendar_read") == "Checking your calendar…")
        #expect(StepWords.tool("location_now") == "Finding where you are…")
        #expect(StepWords.tool("find_slots") == "Using find slots…")
        #expect(Plain.sentence("no model could answer") == "No model could answer. Try again, or ask another way.")
        #expect(Plain.sentence("Done.") == "Done.")
    }
}

@Suite("The conversation on screen")
struct TranscriptTests {
    @Test func aTypedTurnGetsItsAnswerAndCanBeReported() {
        var transcript = Transcript()
        transcript.said("kal ka schedule?", source: 0)
        transcript.apply(.heard(turn: 1, text: "kal ka schedule?"), source: 0)
        transcript.apply(.delta(turn: 1, text: "Kal 10 baje "), source: 0)
        #expect(transcript.entries.last?.streaming == true)
        #expect(transcript.entries.last?.canReport == false)
        transcript.apply(.delta(turn: 1, text: "meeting hai."), source: 0)
        transcript.apply(.done(turn: 1, text: "Kal 10 baje meeting hai.", messageID: 12), source: 0)
        #expect(transcript.entries.map(\.role) == [.you, .ira])
        #expect(transcript.entries[0].turn == 1)
        let answer = transcript.entries[1]
        #expect(answer.text == "Kal 10 baje meeting hai." && answer.messageID == 12 && answer.canReport)
        transcript.markReported(answer.id)
        #expect(!transcript.entries[1].canReport)
    }

    @Test func twoCallsNumberTheirTurnsApart() {
        var transcript = Transcript()
        transcript.apply(.heard(turn: 1, text: "pehli call"), source: 1)
        transcript.apply(.delta(turn: 1, text: "one"), source: 1)
        transcript.apply(.heard(turn: 1, text: "doosri call"), source: 2)
        transcript.apply(.delta(turn: 1, text: "two"), source: 2)
        #expect(transcript.entries.filter { $0.role == .ira }.map(\.text) == ["one", "two"])
    }

    @Test func actionsAndProblemsAreNotes() {
        var transcript = Transcript()
        let card = ActionCard(id: "act_1", tool: "calendar_add", summary: "Add Dentist on Fri 24 Oct, 10:00", tier: 2, canApprove: true, canConfirm: true)
        transcript.apply(.action(turn: 1, action: card), source: 0)
        transcript.apply(.action(turn: 1, action: card), source: 0)  // the same proposal once
        #expect(transcript.entries.filter { $0.action != nil }.count == 1)
        transcript.settle(actionID: "act_1", status: "executed")
        #expect(transcript.entries.first?.action?.statusWords == "Done")
        transcript.apply(.delta(turn: 2, text: "Half"), source: 0)
        transcript.apply(.error("no model could answer", fatal: false), source: 0)
        #expect(transcript.entries.last?.role == .note)
        #expect(transcript.entries.contains { $0.role == .ira && !$0.streaming })
    }
}
