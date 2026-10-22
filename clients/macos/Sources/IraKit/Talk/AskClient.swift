import Foundation

/// The IRA HTTP API, as a signed-in person: ask (streamed), transcribe, speak.
///
/// A device token works only on the device WebSocket (docs/api.md), so this
/// client needs a session token from `POST /v1/auth/login` with
/// `use_cookie: false`. The app uses it only when live voice is not available.
public final class AskClient: @unchecked Sendable {
    public struct Failure: LocalizedError, Equatable {
        public let message: String
        public let status: Int?
        public init(_ message: String, status: Int? = nil) {
            self.message = message
            self.status = status
        }
        public var errorDescription: String? { message }
        public var signedOut: Bool { status == 401 }
    }

    public let server: String
    private let session: URLSession
    private let token: @Sendable () -> String?

    public init(server: String, session: URLSession = .shared, token: @escaping @Sendable () -> String?) {
        self.server = server
        self.session = session
        self.token = token
    }

    private func request(_ path: String, method: String = "GET", json: JSONValue? = nil, body: Data? = nil,
                         contentType: String? = nil, timeout: TimeInterval = 60) throws -> URLRequest {
        guard let url = URL(string: server + path) else { throw Failure("bad server address") }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue(IraApp.userAgent, forHTTPHeaderField: "User-Agent")
        if let token = token() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data(json.encoded().utf8)
        } else if let body {
            request.setValue(contentType ?? "application/octet-stream", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        return request
    }

    static func detail(_ data: Data, status: Int) -> String {
        if let detail = JSONValue.parse(data)?["detail"]?.stringValue { return detail }
        return "the server answered HTTP \(status)"
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure("could not reach \(server): \(Pairing.reason(error))")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(AskClient.detail(data, status: status), status: status)
        }
        return data
    }

    /// Sign in; returns the session token (shown to nobody, kept in the Keychain).
    public static func signIn(server: String, email: String, password: String, session: URLSession = .shared) async throws -> String {
        let client = AskClient(server: server, session: session, token: { nil })
        let body: JSONValue = ["email": .string(email), "password": .string(password), "use_cookie": false]
        let data = try await client.send(try client.request("/v1/auth/login", method: "POST", json: body))
        guard let token = JSONValue.parse(data)?["session_token"]?.stringValue else {
            throw Failure("the server did not give a session")
        }
        return token
    }

    /// `GET /v1/info`: the assistant's name, voice providers and the caller's permissions.
    public func info() async throws -> JSONValue {
        JSONValue.parse(try await send(try request("/v1/info"))) ?? .null
    }

    public func transcribe(wav: Data) async throws -> String {
        let data = try await send(try request("/v1/voice/transcribe", method: "POST", body: wav, contentType: "audio/wav"))
        return JSONValue.parse(data)?["text"]?.stringValue ?? ""
    }

    public func speak(_ text: String) async throws -> Data {
        try await send(try request("/v1/voice/speak", method: "POST", json: ["text": .string(text), "shorten": true]))
    }

    public func approve(actionID: String) async throws -> JSONValue {
        let id = actionID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? actionID
        return JSONValue.parse(try await send(try request("/v1/actions/\(id)/approve", method: "POST", json: [:]))) ?? .null
    }

    public func signOut() async {
        _ = try? await send(try request("/v1/auth/logout", method: "POST", json: [:]))
    }

    /// `POST /v1/ask/stream`: each server-sent event as JSON, in order.
    public func askStream(_ text: String, conversationID: String?) -> AsyncThrowingStream<JSONValue, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var body: [String: JSONValue] = ["text": .string(text)]
                    if let conversationID { body["conversation_id"] = .string(conversationID) }
                    let request = try self.request("/v1/ask/stream", method: "POST", json: .object(body), timeout: 180)
                    let (bytes, response) = try await self.session.bytes(for: request)
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    guard (200..<300).contains(status) else {
                        var data = Data()
                        for try await byte in bytes {
                            data.append(byte)
                            if data.count > 4096 { break }
                        }
                        throw Failure(AskClient.detail(data, status: status), status: status)
                    }
                    var parser = SSEParser()
                    for try await line in bytes.lines {
                        for event in parser.line(line) { continuation.yield(event) }
                    }
                    for event in parser.finish() { continuation.yield(event) }
                    continuation.finish()
                } catch let failure as Failure {
                    continuation.finish(throwing: failure)
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: Failure("could not reach \(self.server): \(Pairing.reason(error))"))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

/// Server-sent events: `data:` lines, an event per blank line. IRA sends one JSON
/// object per event.
public struct SSEParser: Sendable {
    private var data: [String] = []

    public init() {}

    /// Feed one line (without its line break); returns the events it completed.
    public mutating func line(_ line: String) -> [JSONValue] {
        if line.isEmpty { return finish() }
        if line.hasPrefix(":") { return [] }
        if line.hasPrefix("data:") {
            var value = String(line.dropFirst(5))
            if value.hasPrefix(" ") { value.removeFirst() }
            // URLSession's `lines` drops blank lines, so a data line also ends the
            // event before it: IRA never splits one event over several lines.
            let finished = finish()
            data.append(value)
            return finished
        }
        return []
    }

    /// The event in progress, if any.
    public mutating func finish() -> [JSONValue] {
        guard !data.isEmpty else { return [] }
        let text = data.joined(separator: "\n")
        data.removeAll()
        return JSONValue.parse(text).map { [$0] } ?? []
    }
}
