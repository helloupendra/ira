import Foundation
import Testing
@testable import IraPhoneKit

@Suite("Pairing links and codes")
struct PairingParseTests {
    @Test func aPastedLinkNamesItsServer() throws {
        let (server, code) = try Pairing.parse("  https://ira.example.com/pair#code=ABCD-EFGH \n", server: nil)
        #expect(server == "https://ira.example.com")
        #expect(code == "ABCD-EFGH")
    }

    @Test func aLinkWithoutTheDashOrInLowerCaseIsTheSameCode() throws {
        #expect(try Pairing.parse("https://ira.example.com/pair#code=abcdefgh", server: nil).code == "ABCD-EFGH")
    }

    @Test func aLinkUnderAPathKeepsThePath() throws {
        let (server, _) = try Pairing.parse("https://example.com/ira/pair#code=ABCD-EFGH", server: nil)
        #expect(server == "https://example.com/ira")
    }

    @Test func aLinkWinsOverAGivenServer() throws {
        let (server, _) = try Pairing.parse("https://ira.example.com/pair#code=ABCDEFGH", server: "https://other.example.com")
        #expect(server == "https://ira.example.com")
    }

    @Test func theIraLinkFromThePairPage() throws {
        let link = "ira://pair?server=https%3A%2F%2Fira.example.com&code=ABCDEFGH"
        let (server, code) = try Pairing.parse(link, server: nil)
        #expect(server == "https://ira.example.com")
        #expect(code == "ABCD-EFGH")
        #expect(Pairing.fromLink("ira://pair?server=https://ira.example.com") == nil)
        #expect(Pairing.fromLink("ira://settings?code=ABCDEFGH") == nil)
    }

    @Test func aTypedCodeUsesTheGivenServer() throws {
        let (server, code) = try Pairing.parse("abcd-efgh", server: "https://ira.example.com/")
        #expect(server == "https://ira.example.com")
        #expect(code == "ABCD-EFGH")
        #expect(try Pairing.parse("ABCDEFGH", server: "ira.example.com").server == "https://ira.example.com")
    }

    @Test func aTypedCodeWithoutAServerSaysWhatIsMissing() {
        #expect(throws: Pairing.Failure("Type your Ira's address too, for example https://ira.example.com.")) {
            try Pairing.parse("ABCD-EFGH", server: "  ")
        }
    }

    @Test func somethingElseIsRefusedWithWhatToDo() {
        #expect(throws: Pairing.Failure.self) { try Pairing.parse("hello there", server: "https://ira.example.com") }
        #expect(throws: Pairing.Failure("Paste the pairing link, or type the 8-character code.")) {
            try Pairing.parse("", server: nil)
        }
        #expect(Pairing.normalizedCode("ABC-DEFGH") == nil)
        #expect(Pairing.normalizedCode("ABCD-EFGHI") == nil)
    }

    @Test func plainHTTPOnlyOnThisIPhone() throws {
        #expect(try Pairing.checkServer("http://127.0.0.1:8765/") == "http://127.0.0.1:8765")
        #expect(try Pairing.checkServer("http://localhost:8830") == "http://localhost:8830")
        #expect(throws: Pairing.Failure.self) { try Pairing.checkServer("http://ira.example.com") }
        #expect(throws: Pairing.Failure.self) { try Pairing.checkServer("ftp://ira.example.com") }
    }

    @Test func websocketAddresses() {
        #expect(Pairing.websocketURL(server: "https://ira.example.com")?.absoluteString == "wss://ira.example.com/v1/devices/ws")
        #expect(Pairing.websocketURL(server: "http://127.0.0.1:8830/")?.absoluteString == "ws://127.0.0.1:8830/v1/devices/ws")
        #expect(Pairing.websocketURL(server: "https://ira.example.com", path: "/v1/voice/live")?.absoluteString
            == "wss://ira.example.com/v1/voice/live")
    }
}

/// The exchange, against a URLProtocol stub: what Ira for Mac sends, as kind `ios`.
@Suite("Pairing exchange", .serialized)
struct PairingExchangeTests {
    static let token = "irad_" + String(repeating: "x", count: 43)

    @Test func sendsTheCodeAsAnIPhoneAndKeepsTheToken() async throws {
        let session = StubProtocol.session(host: "pair1.example.com") { _, _ in
            .init(status: 200, body: Data("""
                {"device_id": 7, "token": "\(PairingExchangeTests.token)", "kind": "ios", "label": "My iPhone",
                 "skills": ["contacts", "location"], "name": "Ira", "websocket": "/v1/devices/ws"}
                """.utf8))
        }
        let paired = try await Pairing.exchange(server: "https://pair1.example.com", code: "ABCD-EFGH", session: session)
        #expect(paired == Pairing.Paired(
            server: "https://pair1.example.com", token: PairingExchangeTests.token, deviceID: 7, label: "My iPhone",
            skills: ["contacts", "location"], assistant: "Ira"))

        let (request, body) = try #require(StubProtocol.requests("pair1.example.com").first)
        #expect(request.httpMethod == "POST")
        #expect(request.url?.absoluteString == "https://pair1.example.com/v1/devices/pair")
        #expect(request.value(forHTTPHeaderField: "User-Agent") == "ira-ios/\(IraPhone.version)")
        #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
        #expect(try #require(body.flatMap(JSONValue.parse)) == ["code": "ABCD-EFGH", "kind": "ios"])
    }

    @Test func aUsedCodeSaysToMakeANewOne() async {
        let session = StubProtocol.session(host: "pair2.example.com") { _, _ in
            .init(status: 410, body: Data(#"{"detail": "that code is used, expired or unknown"}"#.utf8))
        }
        await #expect(throws: Pairing.Failure("That code is used, expired or mistyped. Make a new one on Your devices, then try again.")) {
            try await Pairing.exchange(server: "https://pair2.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func tooManyWrongCodesSaysToWait() async {
        let session = StubProtocol.session(host: "pair3.example.com") { _, _ in .init(status: 429, body: Data()) }
        await #expect(throws: Pairing.Failure("Too many wrong codes. Wait 15 minutes, then try a new code.")) {
            try await Pairing.exchange(server: "https://pair3.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func anAnswerWithoutADeviceTokenIsRefused() async {
        let session = StubProtocol.session(host: "pair4.example.com") { _, _ in
            .init(status: 200, body: Data(#"{"device_id": 1, "token": "ira_s_session-token-not-a-device"}"#.utf8))
        }
        await #expect(throws: Pairing.Failure.self) {
            try await Pairing.exchange(server: "https://pair4.example.com", code: "ABCD-EFGH", session: session)
        }
    }

    @Test func anUnreachableServerSaysWhy() async {
        let session = StubProtocol.session(host: "pair5.example.com") { _, _ in
            .init(status: 0, body: Data(), error: URLError(.notConnectedToInternet))
        }
        do {
            _ = try await Pairing.exchange(server: "https://pair5.example.com", code: "ABCD-EFGH", session: session)
            Issue.record("expected a failure")
        } catch let failure as Pairing.Failure {
            #expect(failure.message.contains("this iPhone is offline"))
        } catch {
            Issue.record("unexpected \(error)")
        }
    }
}
