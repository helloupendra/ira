import Foundation

/// One WebSocket message.
public enum WebSocketMessage: Equatable, Sendable {
    case text(String)
    case data(Data)
}

/// The connection closed, with the close code or the refused handshake's HTTP status.
public struct WebSocketClosed: Error, Equatable {
    public let code: Int?
    public let httpStatus: Int?
    public let reason: String

    public init(code: Int? = nil, httpStatus: Int? = nil, reason: String = "closed") {
        self.code = code
        self.httpStatus = httpStatus
        self.reason = reason
    }

    /// The token was refused: revoked, unknown, or a handshake answered 401/403.
    public var unauthorized: Bool {
        if let code, [4401, 4403].contains(code) { return true }
        if let httpStatus, [401, 403].contains(httpStatus) { return true }
        return false
    }
}

/// What the protocol clients need from a WebSocket. The app uses URLSession's;
/// tests use a scripted fake, so no test opens a socket.
public protocol WebSocketChannel: AnyObject, Sendable {
    func send(_ message: WebSocketMessage) async throws
    func receive() async throws -> WebSocketMessage
    func close(code: Int)
}

public protocol WebSocketConnector: Sendable {
    func connect(url: URL, headers: [String: String]) async throws -> WebSocketChannel
}

/// URLSessionWebSocketTask behind `WebSocketChannel`. TLS uses the system trust store.
public final class URLSessionWebSocketChannel: WebSocketChannel, @unchecked Sendable {
    private let task: URLSessionWebSocketTask

    init(task: URLSessionWebSocketTask) {
        self.task = task
    }

    public func send(_ message: WebSocketMessage) async throws {
        do {
            switch message {
            case .text(let text): try await task.send(.string(text))
            case .data(let data): try await task.send(.data(data))
            }
        } catch {
            throw closed(error)
        }
    }

    public func receive() async throws -> WebSocketMessage {
        do {
            switch try await task.receive() {
            case .string(let text): return .text(text)
            case .data(let data): return .data(data)
            @unknown default: return .data(Data())
            }
        } catch {
            throw closed(error)
        }
    }

    public func close(code: Int) {
        task.cancel(with: URLSessionWebSocketTask.CloseCode(rawValue: code) ?? .normalClosure, reason: nil)
    }

    private func closed(_ error: Error) -> WebSocketClosed {
        let code = task.closeCode == .invalid ? nil : task.closeCode.rawValue
        let status = (task.response as? HTTPURLResponse)?.statusCode
        let http = status.flatMap { $0 == 101 ? nil : $0 }
        return WebSocketClosed(code: code, httpStatus: http, reason: Pairing.reason(error))
    }
}

public struct URLSessionWebSocketConnector: WebSocketConnector {
    public let session: URLSession
    public let maximumMessageSize: Int

    public init(session: URLSession = .shared, maximumMessageSize: Int = 4 * 1024 * 1024) {
        self.session = session
        self.maximumMessageSize = maximumMessageSize
    }

    public func connect(url: URL, headers: [String: String]) async throws -> WebSocketChannel {
        var request = URLRequest(url: url, timeoutInterval: 20)
        for (name, value) in headers {
            request.setValue(value, forHTTPHeaderField: name)
        }
        let task = session.webSocketTask(with: request)
        task.maximumMessageSize = maximumMessageSize
        task.resume()
        return URLSessionWebSocketChannel(task: task)
    }
}

/// Thrown by `withTimeout` when the time ran out.
public struct TimedOut: Error {}

/// Run `operation`, or throw `TimedOut` after `seconds`.
///
/// Unlike a task group, this returns as soon as the time is up even when the
/// operation does not notice cancellation (a WebSocket receive does not): the
/// operation is cancelled and left to finish on its own, and the caller closes
/// whatever it was waiting on.
public func withTimeout<T: Sendable>(
    _ seconds: Double, _ operation: @escaping @Sendable () async throws -> T
) async throws -> T {
    let once = ResumeOnce<T>()
    return try await withTaskCancellationHandler {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<T, Error>) in
            once.set(continuation)
            let work = Task {
                do { once.resume(.success(try await operation())) } catch { once.resume(.failure(error)) }
            }
            let timer = Task {
                try? await Task.sleep(nanoseconds: UInt64(max(seconds, 0) * 1_000_000_000))
                if once.resume(.failure(TimedOut())) { work.cancel() }
            }
            once.whenDone { timer.cancel() }
        }
    } onCancel: {
        once.resume(.failure(CancellationError()))
    }
}

final class ResumeOnce<T: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<T, Error>?
    private var pending: Result<T, Error>?
    private var finished = false
    private var done: (() -> Void)?

    func set(_ continuation: CheckedContinuation<T, Error>) {
        lock.lock()
        if let pending {
            self.pending = nil
            lock.unlock()
            continuation.resume(with: pending)
            return
        }
        self.continuation = continuation
        lock.unlock()
    }

    func whenDone(_ action: @escaping () -> Void) {
        lock.lock()
        if finished {
            lock.unlock()
            action()
            return
        }
        done = action
        lock.unlock()
    }

    /// Resume with `result` if nothing did yet; true when this call did.
    @discardableResult
    func resume(_ result: Result<T, Error>) -> Bool {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return false
        }
        finished = true
        let continuation = self.continuation
        self.continuation = nil
        if continuation == nil { pending = result }
        let done = self.done
        self.done = nil
        lock.unlock()
        continuation?.resume(with: result)
        done?()
        return true
    }
}

extension NSLock {
    /// Run `body` holding the lock: safe to call from async code, unlike lock() and unlock().
    @discardableResult
    func locked<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
