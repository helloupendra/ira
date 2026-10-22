import Foundation

/// Pairing: trade the one-time code from the Devices page for this iPhone's own token.
///
/// The person opens the pairing link on the iPhone (the pair page offers
/// `ira://pair?server=...&code=...`), pastes the link
/// (`https://ira.example.com/pair#code=ABCD-EFGH`), or types the code and their
/// Ira's address. The app sends the code to `POST /v1/devices/pair` as Ira for
/// Mac does, with kind `ios`, and keeps the token in the Keychain. The code
/// works once, within 10 minutes.
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

        public init(server: String, token: String, deviceID: Int, label: String, skills: [String], assistant: String?) {
            self.server = server
            self.token = token
            self.deviceID = deviceID
            self.label = label
            self.skills = skills
            self.assistant = assistant
        }
    }

    static let codePattern = #"^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$"#

    /// A code as the server shows it: ABCD-EFGH, upper case.
    public static func normalizedCode(_ code: String) -> String? {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.range(of: codePattern, options: .regularExpression) != nil else { return nil }
        let letters = trimmed.replacingOccurrences(of: "-", with: "").uppercased()
        return "\(letters.prefix(4))-\(letters.suffix(4))"
    }

    /// (server, code) from a pasted link, an `ira://pair` link, or a code and the server given.
    public static func parse(_ entry: String, server: String?) throws -> (server: String, code: String) {
        let entry = entry.trimmingCharacters(in: .whitespacesAndNewlines)
        if let found = fromLink(entry) { return found }
        if let code = normalizedCode(entry) {
            let server = server?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if server.isEmpty {
                throw Failure("Type your Ira's address too, for example https://ira.example.com.")
            }
            return (trimSlashes(withScheme(server)), code)
        }
        if entry.isEmpty {
            throw Failure("Paste the pairing link, or type the 8-character code.")
        }
        throw Failure("That is not a pairing link or code. Copy the link from Your devices in the Ira app, then paste it here.")
    }

    /// `https://host/pair#code=ABCD-EFGH` or `ira://pair?server=https://host&code=ABCDEFGH`.
    public static func fromLink(_ text: String) -> (server: String, code: String)? {
        guard let parts = URLComponents(string: text), let scheme = parts.scheme?.lowercased() else { return nil }
        if scheme == "ira" {
            guard parts.host == "pair" || parts.path == "pair" || parts.path == "/pair" else { return nil }
            let items = parts.queryItems ?? []
            guard let server = items.first(where: { $0.name == "server" })?.value,
                let code = items.first(where: { $0.name == "code" })?.value.flatMap(normalizedCode)
            else { return nil }
            return (trimSlashes(server), code)
        }
        guard ["http", "https"].contains(scheme), let host = parts.host, !host.isEmpty,
            parts.path.hasSuffix("/pair"), let fragment = parts.fragment
        else { return nil }
        let pairs = fragment.split(separator: "&").map { $0.split(separator: "=", maxSplits: 1).map(String.init) }
        guard let code = pairs.first(where: { $0.first == "code" && $0.count == 2 }).flatMap({ normalizedCode($0[1]) })
        else { return nil }
        var base = parts
        base.path = String(parts.path.dropLast("/pair".count))
        base.fragment = nil
        base.query = nil
        guard let server = base.string else { return nil }
        return (trimSlashes(server), code)
    }

    /// An address typed without a scheme ("ira.example.com") is https.
    static func withScheme(_ server: String) -> String {
        server.contains("://") ? server : "https://" + server
    }

    /// The server address, checked: http(s) only, and https for anything not on this iPhone.
    public static func checkServer(_ server: String) throws -> String {
        guard let parts = URLComponents(string: server),
            let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
            let host = parts.host, !host.isEmpty
        else {
            throw Failure("Your Ira's address must start with https://.")
        }
        let local = ["127.0.0.1", "localhost", "::1", "[::1]"].contains(host.lowercased())
        if scheme == "http" && !local {
            throw Failure("Use your Ira's https:// address: an iPhone sends nothing to a server over plain http.")
        }
        return trimSlashes(server)
    }

    /// Exchange the code for this iPhone's own device token.
    ///
    /// TLS is checked against the system's trust store, which URLSession uses by default.
    public static func exchange(
        server: String, code: String, session: URLSession = .shared, timeout: TimeInterval = 20
    ) async throws -> Paired {
        let server = try checkServer(server)
        guard let url = URL(string: "\(server)/v1/devices/pair") else {
            throw Failure("Your Ira's address must start with https://.")
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(IraPhone.userAgent, forHTTPHeaderField: "User-Agent")
        let body: JSONValue = ["code": .string(code), "kind": .string(IraPhone.deviceKind)]
        request.httpBody = Data(body.encoded().utf8)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure("Could not reach \(server): \(reason(error)). Check the address and that your iPhone is online.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        switch status {
        case 200..<300: break
        case 410: throw Failure("That code is used, expired or mistyped. Make a new one on Your devices, then try again.")
        case 429: throw Failure("Too many wrong codes. Wait 15 minutes, then try a new code.")
        case 404: throw Failure("\(server) has no pairing for devices. Check it is your Ira's address.")
        default:
            let detail = JSONValue.parse(data)?["detail"]?.stringValue
            throw Failure(detail.map { "Your Ira said: \($0)" } ?? "Your Ira answered HTTP \(status). Try again in a minute.")
        }
        guard let answer = JSONValue.parse(data) else {
            throw Failure("\(server) did not answer like an Ira server. Check the address.")
        }
        let deviceID = answer["device_id"]?.intValue ?? answer["device_id"]?.stringValue.flatMap { Int($0) }
        guard let token = answer["token"]?.stringValue, TokenShape.isDeviceToken(token), let deviceID else {
            throw Failure("Your Ira's answer did not hold a device key. Make a new code and try again.")
        }
        if let kind = answer["kind"]?.stringValue, kind != IraPhone.deviceKind {
            throw Failure("That code is for a \(kind == "mac" ? "Mac" : kind), not an iPhone. Make an iPhone code on Your devices.")
        }
        let label = answer["label"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 } ?? "My iPhone"
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
                return "its certificate is not trusted by this iPhone"
            case NSURLErrorCannotConnectToHost: return "the connection was refused"
            case NSURLErrorTimedOut: return "it did not answer in time"
            case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed: return "there is no such address"
            case NSURLErrorNotConnectedToInternet: return "this iPhone is offline"
            case NSURLErrorAppTransportSecurityRequiresSecureConnection: return "it needs https://"
            case NSURLErrorCancelled: return "it was cancelled"
            default: break
            }
        }
        let text = error.localizedDescription.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return String(text.prefix(160))
    }

    static func trimSlashes(_ text: String) -> String {
        var text = text
        while text.hasSuffix("/") { text.removeLast() }
        return text
    }

    /// The WebSocket address for a server: https -> wss, http -> ws.
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
