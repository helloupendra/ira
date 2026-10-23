import Foundation
@testable import IraPhoneKit

/// A WebSocket that never touches the network: the test pushes what the
/// "server" says and reads what the client sent.
final class FakeChannel: WebSocketChannel, @unchecked Sendable {
    private let lock = NSLock()
    private var queue: [Result<WebSocketMessage, Error>] = []
    private var waiters: [CheckedContinuation<Result<WebSocketMessage, Error>, Never>] = []
    private var sentMessages: [WebSocketMessage] = []
    private(set) var closedWith: Int?
    /// Called for each message the client sends (from its sending task).
    var onSend: ((WebSocketMessage) -> Void)?

    func send(_ message: WebSocketMessage) async throws {
        let closed = lock.withLock { closedWith != nil }
        if closed { throw WebSocketClosed(code: 1000, reason: "closed") }
        lock.withLock { sentMessages.append(message) }
        onSend?(message)
    }

    func receive() async throws -> WebSocketMessage {
        let result: Result<WebSocketMessage, Error> = await withCheckedContinuation { continuation in
            lock.lock()
            if !queue.isEmpty {
                let next = queue.removeFirst()
                lock.unlock()
                continuation.resume(returning: next)
            } else if let code = closedWith {
                lock.unlock()
                continuation.resume(returning: .failure(WebSocketClosed(code: code, reason: "closed")))
            } else {
                waiters.append(continuation)
                lock.unlock()
            }
        }
        return try result.get()
    }

    func close(code: Int) {
        lock.lock()
        if closedWith == nil { closedWith = code }
        let waiters = self.waiters
        self.waiters = []
        lock.unlock()
        for waiter in waiters {
            waiter.resume(returning: .failure(WebSocketClosed(code: code, reason: "closed")))
        }
    }

    private func deliver(_ result: Result<WebSocketMessage, Error>) {
        lock.lock()
        if !waiters.isEmpty {
            let waiter = waiters.removeFirst()
            lock.unlock()
            waiter.resume(returning: result)
        } else {
            queue.append(result)
            lock.unlock()
        }
    }

    func push(_ text: String) { deliver(.success(.text(text))) }
    func push(_ json: JSONValue) { push(json.encoded()) }
    func push(data: Data) { deliver(.success(.data(data))) }
    func fail(_ error: Error) { deliver(.failure(error)) }

    var sent: [WebSocketMessage] { lock.withLock { sentMessages } }

    var sentJSON: [JSONValue] {
        sent.compactMap { message in
            if case .text(let text) = message { return JSONValue.parse(text) }
            return nil
        }
    }

    var sentData: [Data] {
        sent.compactMap { message in
            if case .data(let data) = message { return data }
            return nil
        }
    }

    /// Wait until `predicate` holds for what was sent, or ten seconds pass (CI runners are slow).
    func waitFor(_ predicate: @escaping ([JSONValue]) -> Bool) async -> Bool {
        for _ in 0..<1000 {
            if predicate(sentJSON) { return true }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        return predicate(sentJSON)
    }
}

struct FakeConnector: WebSocketConnector {
    let channel: FakeChannel?
    var error: Error?
    let seen = Seen()

    final class Seen: @unchecked Sendable {
        private let lock = NSLock()
        private var headers: [String: String] = [:]
        private var url: URL?
        func record(_ url: URL, _ headers: [String: String]) {
            lock.withLock {
                self.url = url
                self.headers = headers
            }
        }
        var lastHeaders: [String: String] { lock.withLock { headers } }
        var lastURL: URL? { lock.withLock { url } }
    }

    func connect(url: URL, headers: [String: String]) async throws -> WebSocketChannel {
        seen.record(url, headers)
        if let error { throw error }
        return channel!
    }
}

/// Collects events from any thread.
final class EventLog<T: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [T] = []

    func add(_ item: T) { lock.withLock { items.append(item) } }
    var all: [T] { lock.withLock { items } }

    func waitFor(_ predicate: @escaping ([T]) -> Bool) async -> Bool {
        for _ in 0..<1000 {
            if predicate(all) { return true }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        return predicate(all)
    }
}

/// Answers URLSession requests from a table: no network. Each test uses its own
/// host name, so tests running side by side never see each other's answers.
final class StubProtocol: URLProtocol {
    struct Reply {
        var status: Int
        var body: Data
        var headers: [String: String] = [:]
        var error: Error?
    }

    typealias Handler = (URLRequest, Data?) -> Reply
    nonisolated(unsafe) private static var handlers: [String: Handler] = [:]
    nonisolated(unsafe) private static var seen: [String: [(URLRequest, Data?)]] = [:]
    static let lock = NSLock()

    static func session(host: String, _ handler: @escaping Handler) -> URLSession {
        lock.withLock {
            handlers[host] = handler
            seen[host] = []
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        return URLSession(configuration: configuration)
    }

    static func requests(_ host: String) -> [(URLRequest, Data?)] {
        lock.withLock { seen[host] ?? [] }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let body = request.httpBody ?? request.httpBodyStream.map(StubProtocol.read)
        let host = request.url?.host ?? ""
        let handler = StubProtocol.lock.withLock { () -> Handler? in
            StubProtocol.seen[host, default: []].append((request, body))
            return StubProtocol.handlers[host]
        }
        guard let reply = handler?(request, body) else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        if let error = reply.error {
            client?.urlProtocol(self, didFailWithError: error)
            return
        }
        let response = HTTPURLResponse(
            url: request.url!, statusCode: reply.status, httpVersion: "HTTP/1.1",
            headerFields: reply.headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func read(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}
