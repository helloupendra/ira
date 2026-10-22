import Foundation

/// Pairing: trade the one-time code from the Devices page for this Mac's own token.
///
/// The person pastes the pairing link (`https://ira.example.com/pair#code=ABCD-EFGH`)
/// or types the server's address and the code. The app sends the code to
/// `POST /v1/devices/pair` exactly as the Python companion does (`exchange()` in
/// `clients/mac/ira_mac/pair.py`), and keeps the token it gets in the Keychain.
/// The code works once, within 10 minutes.
public enum Pairing {
    public struct Failure: LocalizedError, Equatable {
        public let message: String
        public init(_ message: String) { self.message = message }
        public var errorDescription: String? { message }
    }

    public struct Paired: Equatable, Sendable {
        public let server: String
        public let token: String
        public let deviceID: Int
        public let label: String
        public let skills: [String]
        /// The name the person gave their assistant ("Ira" by default).
        public let assistant: String?
    }

    static let link = try! NSRegularExpression(
        pattern: #"^(https?://[^#\s]+?)/pair#code=([A-Za-z0-9-]{8,20})$"#)
    static let code = try! NSRegularExpression(pattern: #"^[A-Za-z0-9-]{8,20}$"#)

    /// (server, code) from a pasted link, or from a code and the server given.
    public static func parse(_ entry: String, server: String?) throws -> (server: String, code: String) {
        let entry = entry.trimmingCharacters(in: .whitespacesAndNewlines)
        let range = NSRange(entry.startIndex..., in: entry)
        if let match = link.firstMatch(in: entry, range: range),
            let serverRange = Range(match.range(at: 1), in: entry),
            let codeRange = Range(match.range(at: 2), in: entry)
        {
            return (trimSlashes(String(entry[serverRange])), String(entry[codeRange]))
        }
        if code.firstMatch(in: entry, range: range) != nil {
            let server = server?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if server.isEmpty {
                throw Failure("say which server this code is for")
            }
            return (trimSlashes(server), entry)
        }
        throw Failure("paste the pairing link or type the 8-character code")
    }

    /// The server address, checked: http(s) only, and https for anything not on this Mac.
    public static func checkServer(_ server: String) throws -> String {
        guard let parts = URLComponents(string: server),
            let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
            let host = parts.host, !host.isEmpty
        else {
            throw Failure("the server address must start with http:// or https://")
        }
        let local = ["127.0.0.1", "localhost", "::1", "[::1]"].contains(host.lowercased())
        if scheme == "http" && !local {
            throw Failure("use https:// for a server on another machine")
        }
        return trimSlashes(server)
    }

    /// Exchange the code for this Mac's own device token.
    ///
    /// TLS is checked against the system's trust store, which URLSession uses by default.
    public static func exchange(
        server: String, code: String, session: URLSession = .shared, timeout: TimeInterval = 20
    ) async throws -> Paired {
        let server = try checkServer(server)
        guard let url = URL(string: "\(server)/v1/devices/pair") else {
            throw Failure("the server address must start with http:// or https://")
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(IraApp.userAgent, forHTTPHeaderField: "User-Agent")
        let body: JSONValue = ["code": .string(code), "kind": .string(IraApp.deviceKind)]
        request.httpBody = Data(body.encoded().utf8)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure("could not reach \(server): \(reason(error))")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        switch status {
        case 200..<300: break
        case 410: throw Failure("that code is used, expired or mistyped; make a new one")
        case 429: throw Failure("too many wrong codes; wait 15 minutes")
        default: throw Failure("the server answered HTTP \(status)")
        }
        guard let answer = JSONValue.parse(data) else {
            throw Failure("\(server) did not answer like an Ira server")
        }
        let deviceID = answer["device_id"]?.intValue ?? answer["device_id"]?.stringValue.flatMap { Int($0) }
        guard let token = answer["token"]?.stringValue, !token.isEmpty, let deviceID else {
            throw Failure("the server's answer did not hold a device token")
        }
        let label = answer["label"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 } ?? "My Mac"
        let skills = (answer["skills"]?.arrayValue ?? []).compactMap(\.stringValue)
        return Paired(
            server: server, token: token, deviceID: deviceID, label: label, skills: skills,
            assistant: answer["name"]?.stringValue)
    }

    /// Why a request failed, in a few words.
    public static func reason(_ error: Error) -> String {
        let error = error as NSError
        if error.domain == NSURLErrorDomain {
            switch error.code {
            case NSURLErrorServerCertificateUntrusted, NSURLErrorServerCertificateHasBadDate,
                NSURLErrorServerCertificateHasUnknownRoot, NSURLErrorServerCertificateNotYetValid,
                NSURLErrorSecureConnectionFailed:
                return "its certificate is not trusted by this Mac"
            case NSURLErrorCannotConnectToHost: return "connection refused"
            case NSURLErrorTimedOut: return "it did not answer in time"
            case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed: return "no such host"
            case NSURLErrorNotConnectedToInternet: return "this Mac is offline"
            default: break
            }
        }
        let text = error.localizedDescription.split(whereSeparator: \.isWhitespace).joined(
            separator: " ")
        return String(text.prefix(160))
    }

    static func trimSlashes(_ text: String) -> String {
        var text = text
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }

    /// The device WebSocket's address for a server: https -> wss, http -> ws.
    public static func websocketURL(server: String, path: String = "/v1/devices/ws") -> URL? {
        let base = trimSlashes(server)
        if base.hasPrefix("https://") {
            return URL(string: "wss://" + base.dropFirst("https://".count) + path)
        }
        if base.hasPrefix("http://") {
            return URL(string: "ws://" + base.dropFirst("http://".count) + path)
        }
        return nil
    }
}
