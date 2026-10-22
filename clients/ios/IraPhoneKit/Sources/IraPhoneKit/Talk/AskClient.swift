import Foundation

/// The IRA HTTP API for this iPhone's person: ask (streamed or whole), speak,
/// answer a proposed action, and report an answer.
///
/// It signs in with the device token: a paired device may talk to Ira for its
/// person, with at most their ask, voice and actions permissions
/// (docs/devices.md).
public final class AskClient: @unchecked Sendable {
    public struct Failure: LocalizedError, Equatable {
        public let message: String
        public let status: Int?
        public init(_ message: String, status: Int? = nil) {
            self.message = message
            self.status = status
        }
        public var errorDescription: String? { message }
        /// The server no longer knows this iPhone's key.
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

    func request(_ path: String, method: String = "GET", json: JSONValue? = nil, timeout: TimeInterval = 60) throws -> URLRequest {
        guard let url = URL(string: server + path) else { throw Failure("Your Ira's address is not valid. Pair again.") }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue(IraPhone.userAgent, forHTTPHeaderField: "User-Agent")
        if let token = token() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let json {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data(json.encoded().utf8)
        }
        return request
    }

    /// The server's own sentence for a failed request, or its status.
    public static func detail(_ data: Data, status: Int) -> String {
        if let detail = JSONValue.parse(data)?["detail"]?.stringValue { return detail }
        switch status {
        case 401: return "Your Ira no longer knows this iPhone. Pair it again."
        case 403: return "Your Ira account may not do this."
        case 404: return "Your Ira does not have this. It may need an update."
        case 429: return "Too many requests. Wait a minute, then try again."
        case 500...599: return "Your Ira had a problem (HTTP \(status)). Try again in a minute."
        default: return "Your Ira answered HTTP \(status)."
        }
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure(AskClient.unreachable(server, error))
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw Failure(AskClient.detail(data, status: status), status: status)
        }
        return data
    }

    static func unreachable(_ server: String, _ error: Error) -> String {
        "Could not reach your Ira: \(Pairing.reason(error)). Check that your iPhone is online, then try again."
    }

    /// `GET /v1/info`: the assistant's name, voice, live calls and the caller's permissions.
    public func info() async throws -> ServerInfo {
        ServerInfo(JSONValue.parse(try await send(try request("/v1/info"))) ?? .null)
    }

    /// `POST /v1/ask`: the whole answer at once (Siri).
    public func ask(_ text: String, conversationID: String?, timeout: TimeInterval = 50) async throws -> Answer {
        var body: [String: JSONValue] = ["text": .string(text)]
        if let conversationID { body["conversation_id"] = .string(conversationID) }
        let data = try await send(try request("/v1/ask", method: "POST", json: .object(body), timeout: timeout))
        guard let answer = JSONValue.parse(data) else { throw Failure("Your Ira's answer could not be read.") }
        return Answer(answer)
    }

    /// `POST /v1/voice/speak`: one sentence as MP3, in the person's own Ira voice.
    public func speak(_ text: String) async throws -> Data {
        try await send(try request("/v1/voice/speak", method: "POST", json: ["text": .string(text), "shorten": true], timeout: 30))
    }

    private static func actionPath(_ id: String, _ verb: String) -> String {
        let id = id.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_"))) ?? id
        return "/v1/actions/\(id)/\(verb)"
    }

    /// A proposal's answer: approve (Tier 2, the person's yes), cancel, or confirm with the PIN.
    /// The answer always holds a `status`, also when the HTTP status is an error.
    private func decide(_ path: String, json: JSONValue) async throws -> ActionOutcome {
        let request = try request(path, method: "POST", json: json)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure(AskClient.unreachable(server, error))
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard let outcome = JSONValue.parse(data), outcome["status"]?.stringValue != nil else {
            throw Failure(AskClient.detail(data, status: status), status: status)
        }
        return ActionOutcome(outcome)
    }

    /// Say yes to a Tier 2 proposal. Only the person who asked may.
    public func approve(actionID: String) async throws -> ActionOutcome {
        try await decide(AskClient.actionPath(actionID, "approve"), json: [:])
    }

    public func cancel(actionID: String) async throws -> ActionOutcome {
        try await decide(AskClient.actionPath(actionID, "cancel"), json: [:])
    }

    /// Confirm a Tier 3 action with the person's PIN, typed in the app (never spoken).
    public func confirm(actionID: String, pin: String) async throws -> ActionOutcome {
        try await decide(AskClient.actionPath(actionID, "confirm"), json: ["pin": .string(pin)])
    }

    /// `POST /v1/me/reports`: report one of Ira's answers to the person who runs this Ira.
    public func report(messageID: Int, reason: ReportReason, note: String?) async throws {
        var body: [String: JSONValue] = ["message_id": .number(Double(messageID)), "reason": .string(reason.rawValue)]
        if let note = note?.trimmingCharacters(in: .whitespacesAndNewlines), !note.isEmpty {
            body["note"] = .string(String(note.prefix(500)))
        }
        do {
            _ = try await send(try request("/v1/me/reports", method: "POST", json: .object(body)))
        } catch let failure as Failure where failure.status == 404 {
            throw Failure("That answer is no longer on your Ira, so it cannot be reported.", status: 404)
        }
    }

    /// `POST /v1/ask/stream`: each server-sent event, in order.
    public func askStream(_ text: String, conversationID: String?) -> AsyncThrowingStream<AskEvent, Error> {
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
                        for event in parser.line(line) { continuation.yield(AskEvent(event)) }
                    }
                    for event in parser.finish() { continuation.yield(AskEvent(event)) }
                    continuation.finish()
                } catch let failure as Failure {
                    continuation.finish(throwing: failure)
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    if (error as NSError).code == NSURLErrorCancelled {
                        continuation.finish()
                    } else {
                        continuation.finish(throwing: Failure(AskClient.unreachable(self.server, error)))
                    }
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
