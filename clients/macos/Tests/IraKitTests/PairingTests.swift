import Foundation
import Testing
@testable import IraKit

@Suite("Pairing")
struct PairingParseTests {
    @Test func aPastedLinkNamesItsServer() throws {
        let (server, code) = try Pairing.parse("  https://ira.example.com/pair#code=ABCD-EFGH \n", server: nil)
        #expect(server == "https://ira.example.com")
        #expect(code == "ABCD-EFGH")
    }

    @Test func aLinkWinsOverAGivenServer() throws {
        let (server, _) = try Pairing.parse("https://ira.example.com/pair#code=ABCDEFGH", server: "https://other.example.com")
        #expect(server == "https://ira.example.com")
    }

    @Test func aTypedCodeUsesTheGivenServer() throws {
        let (server, code) = try Pairing.parse("ABCD-EFGH", server: "https://ira.example.com/")
        #expect(server == "https://ira.example.com")
        #expect(code == "ABCD-EFGH")
    }

    @Test func aTypedCodeWithoutAServerIsRefused() {
        #expect(throws: Pairing.Failure("say which server this code is for")) {
            try Pairing.parse("ABCD-EFGH", server: nil)
        }
    }

    @Test func somethingElseIsRefused() {
        #expect(throws: Pairing.Failure("paste the pairing link or type the 8-character code")) {
            try Pairing.parse("hello there", server: "https://ira.example.com")
        }
    }

    @Test func plainHTTPOnlyOnThisMac() throws {
        #expect(try Pairing.checkServer("http://127.0.0.1:8765/") == "http://127.0.0.1:8765")
        #expect(try Pairing.checkServer("http://localhost:8830") == "http://localhost:8830")
        #expect(throws: Pairing.Failure("use https:// for a server on another machine")) {
            try Pairing.checkServer("http://ira.example.com")
        }
        #expect(throws: Pairing.Failure("the server address must start with http:// or https://")) {
            try Pairing.checkServer("ftp://ira.example.com")
        }
    }

    @Test func websocketAddresses() {
        #expect(Pairing.websocketURL(server: "https://ira.example.com")?.absoluteString == "wss://ira.example.com/v1/devices/ws")
        #expect(Pairing.websocketURL(server: "http://127.0.0.1:8830/")?.absoluteString == "ws://127.0.0.1:8830/v1/devices/ws")
        #expect(Pairing.websocketURL(server: "https://ira.example.com", path: "/v1/voice/live")?.absoluteString
            == "wss://ira.example.com/v1/voice/live")
    }
}

/// The exchange, against a URLProtocol stub: exactly what the Python companion sends.
@Suite("Pairing exchange", .serialized)
struct PairingExchangeTests {
    static let token = "irad_" + String(repeating: "x", count: 43)

    @Test func sendsTheCodeAndKeepsTheToken() async throws {
        let session = StubProtocol.session(host: "pair9.example.com") { _, _ in
            .init(status: 200, body: Data("""
                {"device_id": 3, "token": "\(PairingExchangeTests.token)", "kind": "mac", "label": "Studio Mac",
                 "skills": ["files", "screen"], "name": "Ira", "websocket": "/v1/devices/ws"}
                """.utf8))
        }
        let paired = try await Pairing.exchange(server: "https://pair9.example.com", code: "ABCD-EFGH", session: session)
        #expect(paired == Pairing.Paired(
            server: "https://pair9.example.com", token: PairingExchangeTests.token, deviceID: 3, label: "Studio Mac",
            skills: ["files", "screen"], assistant: "Ira"))

        let (request, body) = try #require(StubProtocol.requests("pair9.example.com").first)
        #expect(request.httpMethod == "POST")
        #expect(request.url?.absoluteString == "https://pair9.example.com/v1/devices/pair")
        #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(request.value(forHTTPHeaderField: "User-Agent") == "ira-mac-app/\(IraApp.version)")
        #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
        let sent = try #require(body.flatMap(JSONValue.parse))
        #expect(sent == ["code": "ABCD-EFGH", "kind": "mac"])
    }

    @Test func aLabelDefaultsToMyMac() async throws {
        let session = StubProtocol.session(host: "127.0.0.1") { _, _ in
            .init(status: 200, body: Data(#"{"device_id": "7", "token": "\#(PairingExchangeTests.token)"}"#.utf8))
        }
        let paired = try await Pairing.exchange(server: "http://127.0.0.1:8830", code: "ABCDEFGH", session: session)
        #expect(paired.label == "My Mac")
        #expect(paired.deviceID == 7)
        #expect(paired.skills == [])
    }

    @Test(arguments: [
        (410, "that code is used, expired or mistyped; make a new one"),
        (429, "too many wrong codes; wait 15 minutes"),
        (500, "the server answered HTTP 500"),
    ])
    func serverRefusals(status: Int, message: String) async {
        let session = StubProtocol.session(host: "pair11.example.com") { _, _ in .init(status: status, body: Data(#"{"detail": "no"}"#.utf8)) }
        await #expect(throws: Pairing.Failure(message)) {
            try await Pairing.exchange(server: "https://pair11.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func notAnIraServer() async {
        let session = StubProtocol.session(host: "pair12.example.com") { _, _ in .init(status: 200, body: Data("<html>hello</html>".utf8)) }
        await #expect(throws: Pairing.Failure("https://pair12.example.com did not answer like an Ira server")) {
            try await Pairing.exchange(server: "https://pair12.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func anAnswerWithoutAToken() async {
        let session = StubProtocol.session(host: "pair13.example.com") { _, _ in .init(status: 200, body: Data(#"{"device_id": 3}"#.utf8)) }
        await #expect(throws: Pairing.Failure("the server's answer did not hold a device token")) {
            try await Pairing.exchange(server: "https://pair13.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func unreachable() async {
        let session = StubProtocol.session(host: "pair14.example.com") { _, _ in
            .init(status: 0, body: Data(), error: URLError(.cannotConnectToHost))
        }
        await #expect(throws: Pairing.Failure("could not reach https://pair14.example.com: connection refused")) {
            try await Pairing.exchange(server: "https://pair14.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func plainHTTPToAnotherMachineNeverLeaves() async {
        let session = StubProtocol.session(host: "pair15.example.com") { _, _ in .init(status: 200, body: Data()) }
        await #expect(throws: Pairing.Failure("use https:// for a server on another machine")) {
            try await Pairing.exchange(server: "http://pair15.example.com", code: "ABCD-EFGH", session: session)
        }
        #expect(StubProtocol.requests("pair15.example.com").isEmpty)
    }
}

@Suite("Secrets and logs")
struct SecretsAndLogTests {
    @Test func tokenShapes() {
        #expect(TokenShape.isDeviceToken("irad_" + String(repeating: "A", count: 43)))
        #expect(!TokenShape.isDeviceToken("irad_short"))
        #expect(!TokenShape.isDeviceToken("ira_s_" + String(repeating: "A", count: 43)))
        #expect(TokenShape.isSessionToken("ira_s_" + String(repeating: "A", count: 43)))
    }

    @Test func logsMaskTokensCodesAndQueries() {
        let line = IraLog.redact(
            "token irad_abcdefghijklmnop and ira_s_secretsecret at https://ira.example.com/pair#code=ABCD-EFGH "
                + "and https://ira.example.com/x?token=abc code=WXYZ-1234 Bearer abc.def")
        #expect(!line.contains("abcdefghijklmnop"))
        #expect(!line.contains("secretsecret"))
        #expect(!line.contains("ABCD-EFGH"))
        #expect(!line.contains("token=abc"))
        #expect(!line.contains("WXYZ-1234"))
        #expect(!line.contains("abc.def"))
        #expect(line.contains("https://ira.example.com/pair"))
        #expect(IraLog.redact(String(repeating: "a", count: 900)).count == IraLog.maxLine + 3)
    }

    @Test func memoryStoreRoundTrip() throws {
        let store = MemorySecretStore()
        try store.save("irad_x", account: SecretAccount.device)
        #expect(store.load(SecretAccount.device) == "irad_x")
        store.delete(SecretAccount.device)
        #expect(store.load(SecretAccount.device) == nil)
    }

    @Test func settingsForgetThePairingButNeverHoldAToken() {
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        let settings = AppSettings(defaults: defaults)
        settings.server = "https://ira.example.com"
        settings.deviceID = 3
        settings.rememberConversation("abc")
        #expect(settings.recentConversation() == "abc")
        #expect(settings.recentConversation(now: Date().addingTimeInterval(3600)) == nil)
        settings.forgetPairing()
        #expect(settings.server == "")
        #expect(settings.deviceID == nil)
        #expect(settings.hotKeyCode == 49)
        #expect(settings.hotKeyModifiers == 0x0800)
        let everything = defaults.dictionaryRepresentation().values.map { "\($0)" }.joined()
        #expect(!everything.contains("irad_"))
    }
}

/// The two pairing rules that keep a person from losing their pairing.
@Suite("Keeping the pairing")
struct PairingRecordTests {
    func record(server: String = "https://ira.example.com", token: String? = "irad_" + String(repeating: "t", count: 43))
        -> (PairingRecord, MemorySecretStore, AppSettings)
    {
        let defaults = UserDefaults(suiteName: "ira-tests-\(UUID().uuidString)")!
        let settings = AppSettings(defaults: defaults)
        settings.server = server
        settings.firstRunDone = true
        let store = MemorySecretStore(token.map { [SecretAccount.device: $0] } ?? [:])
        return (PairingRecord(settings: settings, secrets: store), store, settings)
    }

    @Test(arguments: [Int32(-25293), Int32(-25308), Int32(-128)])  // auth failed, interaction not allowed, cancelled
    func anUnreadableKeyIsNeverUnpaired(status: Int32) {
        let (record, store, settings) = record()
        store.failing[SecretAccount.device] = status
        #expect(record.status == .keyUnreadable(status))
        // Looking again changes nothing, and nothing was deleted or forgotten.
        _ = record.status
        #expect(store.deletions.isEmpty)
        #expect(settings.server == "https://ira.example.com")
        #expect(settings.firstRunDone)
        store.failing[SecretAccount.device] = nil
        #expect(record.status == .paired)
    }

    @Test func onlyRemovingOnPurposeForgets() throws {
        let (record, store, settings) = record()
        #expect(record.status == .paired)
        // Pairing again replaces the key; it never deletes it first.
        try record.adopt(server: "https://ira.example.com", token: "irad_" + String(repeating: "n", count: 43), deviceID: 9, label: "Mac")
        #expect(store.deletions.isEmpty)
        #expect(store.load(SecretAccount.device)?.hasPrefix("irad_nnn") == true)
        #expect(settings.deviceID == 9)
        record.removeOnPurpose()
        #expect(store.deletions.contains(SecretAccount.device))
        #expect(settings.server == "")
        #expect(!settings.firstRunDone)
        #expect(record.status == .unpaired)
    }

    @Test func aMissingKeyOrServerIsUnpaired() {
        #expect(record(token: nil).0.status == .unpaired)
        #expect(record(server: "").0.status == .unpaired)
    }
}
