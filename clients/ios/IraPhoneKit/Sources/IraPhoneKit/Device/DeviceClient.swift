import Foundation

/// What the device client runs: the tools this iPhone offers.
public protocol ToolRunner: Sendable {
    /// The tools for the hello: name, description, JSON Schema parameters, skill, tier.
    var definitions: [JSONValue] { get }
    /// Run one tool. A `ToolFailure`'s message goes back to Ira as the error.
    func call(_ name: String, args: JSONValue) async throws -> JSONValue
}

/// A tool could not do what was asked; the message is safe to send to the server.
public struct ToolFailure: LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

public enum DeviceState: Equatable, Sendable {
    case connecting
    case connected(deviceID: Int?, skills: [String])
    /// Waiting before the next try, with why.
    case waiting(seconds: Double, reason: String)
    /// The server refused this iPhone's token: it was removed, or never paired.
    case refused
    /// The Keychain did not hand over the key (nothing was forgotten).
    case keyUnavailable
    case stopped
}

/// Holds this iPhone's device WebSocket and answers the server's calls, as Ira
/// for Mac does:
///
/// * says hello with the tools, waits for welcome, then answers each `call`
///   with a `result` (several at once), and pings every 30 seconds;
/// * hears nothing for 90 seconds: drops the connection and reconnects;
/// * reconnects with a growing delay (1 s up to 60 s, with jitter); a connection
///   that lasted a minute starts the delays again from 1 s;
/// * after a revoked or unknown token (4401, 4403, or HTTP 401/403 on the
///   handshake) it waits 5 minutes between tries and says why.
///
/// iOS suspends an app soon after it leaves the screen, which ends the
/// connection; the app stops the client then, and starts it again when it comes
/// back (or keeps it while a call holds the app awake).
public final class DeviceClient: @unchecked Sendable {
    public struct Timing: Sendable {
        public var ping: Double = DeviceProtocol.pingSeconds
        public var silence: Double = DeviceProtocol.silenceSeconds
        public var backoff: [Double] = [1, 2, 5, 10, 30, 60]
        public var refusedWait: Double = 300
        public var stable: Double = 60
        public var jitter = true
        public init() {}
    }

    public let url: URL
    let token: @Sendable () -> String?
    let tools: ToolRunner
    let label: String
    let connector: WebSocketConnector
    let timing: Timing
    let onState: @Sendable (DeviceState) -> Void
    let log: IraLog

    let lock = NSLock()
    var runner: Task<Void, Never>?
    var wake: CheckedContinuation<Void, Never>?
    var pauses = 0
    var stopped = false
    var current: WebSocketChannel?

    public init(
        url: URL,
        token: @escaping @Sendable () -> String?,
        tools: ToolRunner,
        label: String,
        connector: WebSocketConnector = URLSessionWebSocketConnector(),
        timing: Timing = Timing(),
        log: IraLog = .shared,
        onState: @escaping @Sendable (DeviceState) -> Void = { _ in }
    ) {
        self.url = url
        self.token = token
        self.tools = tools
        self.label = label
        self.connector = connector
        self.timing = timing
        self.log = log
        self.onState = onState
    }

    func headers(_ token: String?) -> [String: String] {
        var headers = ["User-Agent": IraPhone.userAgent]
        if let token {
            // In a header, never in the address, so no proxy logs it.
            headers["Authorization"] = "Bearer \(token)"
        }
        return headers
    }

    // MARK: Running

    public var isRunning: Bool { lock.withLock { runner != nil } }

    public func start() {
        lock.withLock {
            guard runner == nil else { return }
            stopped = false
            runner = Task { [weak self] in await self?.runForever() }
        }
    }

    /// Stop: close the connection now and do not reconnect until `start`.
    public func stop() {
        let (channel, runner, wake): (WebSocketChannel?, Task<Void, Never>?, CheckedContinuation<Void, Never>?) =
            lock.withLock {
                stopped = true
                let taken = (current, self.runner, self.wake)
                self.runner = nil
                self.wake = nil
                return taken
            }
        channel?.close(code: 1000)
        runner?.cancel()
        wake?.resume()
        onState(.stopped)
    }

    /// Skip the current wait and try again now (the app came back, the network returned).
    public func reconnectNow() {
        let wake = lock.withLock {
            let wake = self.wake
            self.wake = nil
            return wake
        }
        wake?.resume()
    }

    var isStopped: Bool {
        lock.withLock { stopped } || Task.isCancelled
    }
}

/// Sends frames one at a time, so concurrent results never interleave.
actor FrameSender {
    let channel: WebSocketChannel

    init(channel: WebSocketChannel) {
        self.channel = channel
    }

    func send(_ text: String) async throws {
        try await channel.send(.text(text))
    }
}
