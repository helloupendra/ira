import Foundation

/// What the device client runs: the tools this Mac offers.
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
    /// The server refused this Mac's token: it was removed, or never paired.
    case refused
    /// The Keychain did not hand over this Mac's key (nothing was forgotten).
    case keyUnavailable
    case stopped
}

/// Holds this Mac's device WebSocket and answers the server's calls.
///
/// The same behaviour as the retired Python companion's daemon:
///
/// * says hello with the tools, waits for welcome, then answers each `call`
///   with a `result` (several at once), and pings every 30 seconds;
/// * hears nothing for 90 seconds: drops the connection and reconnects;
/// * reconnects with a growing delay (1 s up to 60 s, with jitter); a connection
///   that lasted a minute starts the delays again from 1 s;
/// * after a revoked or unknown token (4401, 4403, or HTTP 401/403 on the
///   handshake) it waits 5 minutes between tries and says why.
public final class DeviceClient: @unchecked Sendable {
    public struct Timing: Sendable {
        public var ping: Double = DeviceProtocol.pingSeconds
        public var silence: Double = DeviceProtocol.silenceSeconds
        public var backoff: [Double] = [1, 2, 5, 10, 30, 60]
        public var refusedWait: Double = 300
        public var stable: Double = 60
        public var jitter = true
        /// The server takes one event per 30 seconds; a second to spare.
        public var eventSpacing: Double = 31
        public init() {}
    }

    public let url: URL
    private let token: @Sendable () -> String?
    private let tools: ToolRunner
    private let label: String
    private let connector: WebSocketConnector
    private let timing: Timing
    private let onState: @Sendable (DeviceState) -> Void
    /// The person's assistant name and wake phrase, from each welcome.
    public var onWelcome: @Sendable (String?, String?) -> Void = { _, _ in }
    /// A change in the person's Drop, from another of their devices.
    public var onDrop: @Sendable (DropFrame) -> Void = { _ in }
    private let log: IraLog

    private let lock = NSLock()
    private var runner: Task<Void, Never>?
    private var wake: CheckedContinuation<Void, Never>?
    private var pauses = 0
    private var stopped = false
    private var current: WebSocketChannel?
    private var outbox: [JSONValue] = []
    private var observations: [JSONValue] = []
    private var lastEvent: Date?
    private var outboxWake: CheckedContinuation<Void, Never>?
    private var currentSkills: [String] = []

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

    private var headers: [String: String] {
        var headers = ["User-Agent": IraApp.userAgent]
        if let token = token() {
            // In a header, never in the address, so no proxy logs it.
            headers["Authorization"] = "Bearer \(token)"
        }
        return headers
    }

    // MARK: Events

    /// Announce something the person should hear ("task t1 is done"). Events wait
    /// in an outbox while offline and go out at most one per 30 seconds.
    public func announce(event: String, title: String, text: String, data: JSONValue = .object([:])) {
        let frame: JSONValue = ["type": "event", "event": .string(event), "title": .string(title), "text": .string(text), "data": data]
        let wake: CheckedContinuation<Void, Never>? = lock.locked {
            outbox.append(frame)
            if outbox.count > 50 { outbox.removeFirst(outbox.count - 50) }
            let wake = outboxWake
            outboxWake = nil
            return wake
        }
        wake?.resume()
    }

    /// Queue an observation (the routine skill); it goes out as soon as this Mac
    /// is connected, with no spacing. At most 500 wait while offline.
    public func observe(_ frame: JSONValue) {
        let wake: CheckedContinuation<Void, Never>? = lock.locked {
            observations.append(frame)
            if observations.count > 500 { observations.removeFirst(observations.count - 500) }
            let wake = outboxWake
            outboxWake = nil
            return wake
        }
        wake?.resume()
    }

    /// The skills the person switched on for this Mac, as the server last said.
    public var skills: [String] { lock.locked { currentSkills } }

    /// Whether this Mac is connected now.
    public var isConnected: Bool { lock.locked { current != nil && !currentSkillsUnknown } }
    private var currentSkillsUnknown = true

    private func waitForOutbox() async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            let ready: Bool = lock.locked {
                if !outbox.isEmpty || !observations.isEmpty { return true }
                outboxWake = continuation
                return false
            }
            if ready { continuation.resume() }
        }
    }

    private func eventSender(_ sender: FrameSender) async {
        while !Task.isCancelled {
            await waitForOutbox()
            if Task.isCancelled { return }
            // Observations first, all of them: they carry their own times.
            while let frame = lock.locked({ observations.first }) {
                do {
                    try await sender.send(frame.encoded())
                } catch {
                    return  // kept for the next connection
                }
                lock.locked { if !observations.isEmpty { observations.removeFirst() } }
            }
            guard lock.locked({ !outbox.isEmpty }) else { continue }
            if let last = lock.locked({ lastEvent }) {
                let wait = timing.eventSpacing - Date().timeIntervalSince(last)
                if wait > 0 { try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000)) }
            }
            guard let frame = lock.locked({ outbox.first }) else { continue }
            do {
                try await sender.send(frame.encoded())
            } catch {
                return  // still in the outbox for the next connection
            }
            lock.locked {
                if !outbox.isEmpty { outbox.removeFirst() }
                lastEvent = Date()
            }
            log.info("sent event \(frame["event"]?.stringValue ?? "")")
        }
    }

    private func cancelEventWait() {
        let wake: CheckedContinuation<Void, Never>? = lock.locked {
            let wake = outboxWake
            outboxWake = nil
            return wake
        }
        wake?.resume()
    }

    // MARK: Running

    public func start() {
        lock.lock()
        defer { lock.unlock() }
        guard runner == nil else { return }
        stopped = false
        runner = Task { [weak self] in await self?.runForever() }
    }

    /// Stop for good: close the connection now and do not reconnect.
    public func stop() {
        lock.lock()
        stopped = true
        let channel = current
        let runner = self.runner
        self.runner = nil
        let wake = self.wake
        self.wake = nil
        lock.unlock()
        channel?.close(code: 1000)
        runner?.cancel()
        wake?.resume()
        onState(.stopped)
    }

    /// Skip the current wait and try again now (the Mac woke up, the network came back).
    public func reconnectNow() {
        lock.lock()
        let wake = self.wake
        self.wake = nil
        lock.unlock()
        wake?.resume()
    }

    private func setCurrent(_ channel: WebSocketChannel?) {
        lock.lock()
        current = channel
        lock.unlock()
    }

    private var isStopped: Bool {
        lock.lock()
        defer { lock.unlock() }
        return stopped || Task.isCancelled
    }

    func runForever() async {
        var attempt = 0
        while !isStopped {
            guard let token = token() else {
                log.warning("this Mac's key could not be read from the Keychain; trying again later")
                onState(.keyUnavailable)
                await pause(timing.refusedWait)
                continue
            }
            onState(.connecting)
            let started = Date()
            let closed = await runOnce(token: token)
            if isStopped { return }
            if closed?.unauthorized == true {
                log.warning("the server refused this Mac's token: it was removed or never paired")
                onState(.refused)
                await pause(timing.refusedWait)
                attempt = 0
                continue
            }
            if Date().timeIntervalSince(started) >= timing.stable {
                attempt = 0
            }
            var delay = timing.backoff[min(attempt, timing.backoff.count - 1)]
            attempt += 1
            if timing.jitter { delay *= Double.random(in: 0.8...1.2) }
            log.info(String(format: "reconnecting in %.0fs", delay))
            onState(.waiting(seconds: delay, reason: closed?.reason ?? "the connection ended"))
            await pause(delay)
        }
    }

    /// Sleep, unless `reconnectNow` or `stop` comes first.
    private func pause(_ seconds: Double) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            lock.lock()
            if stopped {
                lock.unlock()
                continuation.resume()
                return
            }
            pauses += 1
            let id = pauses
            wake = continuation
            lock.unlock()
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                self?.endPause(id)
            }
        }
    }

    private func endPause(_ id: Int) {
        lock.lock()
        guard id == pauses, let wake else {
            lock.unlock()
            return
        }
        self.wake = nil
        lock.unlock()
        wake.resume()
    }

    /// One connection, from hello until it closes. Returns how it closed, if known.
    public func runOnce(token: String) async -> WebSocketClosed? {
        let channel: WebSocketChannel
        do {
            channel = try await connector.connect(url: url, headers: headers)
        } catch {
            let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: Pairing.reason(error))
            log.warning("could not connect: \(closed.reason)")
            return closed
        }
        setCurrent(channel)
        defer {
            setCurrent(nil)
            channel.close(code: 1000)
        }
        let sender = FrameSender(channel: channel)
        do {
            try await sender.send(DeviceProtocol.hello(label: label, tools: tools.definitions).encoded())
            let first = try await withTimeout(timing.silence) { try await channel.receive() }
            guard case .text(let text) = first,
                case .welcome(let deviceID, _, let skills, let assistant, let wakePhrase) = try DeviceProtocol.decode(text)
            else {
                if case .text(let text) = first, case .error(let reason)? = try? DeviceProtocol.decode(text) {
                    log.warning("the server refused the hello: \(reason)")
                    return WebSocketClosed(code: 4400, reason: "the server refused the hello: \(reason)")
                }
                log.warning("the server did not welcome this Mac")
                return WebSocketClosed(reason: "the server did not welcome this Mac")
            }
            log.info("connected as device \(deviceID.map(String.init) ?? "?") with skills \(skills)")
            lock.locked {
                currentSkills = skills
                currentSkillsUnknown = false
            }
            defer { lock.locked { currentSkillsUnknown = true } }
            onState(.connected(deviceID: deviceID, skills: skills))
            onWelcome(assistant, wakePhrase)
            return await session(channel: channel, sender: sender, deviceID: deviceID, skills: skills)
        } catch {
            let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: "the connection ended")
            log.info("connection ended: \(closed.code.map(String.init) ?? "") \(closed.reason)")
            return closed
        }
    }

    private func session(
        channel: WebSocketChannel, sender: FrameSender, deviceID: Int?, skills: [String]
    ) async -> WebSocketClosed? {
        let pinger = Task { [timing] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(timing.ping * 1_000_000_000))
                if Task.isCancelled { return }
                try? await sender.send(DeviceProtocol.ping.encoded())
            }
        }
        let events = Task { await self.eventSender(sender) }
        var calls: [Task<Void, Never>] = []
        // Each tool's skill, as this Mac offered it.
        var skillOf: [String: String] = [:]
        for tool in tools.definitions {
            if let name = tool["name"]?.stringValue, let skill = tool["skill"]?.stringValue { skillOf[name] = skill }
        }
        defer {
            pinger.cancel()
            events.cancel()
            cancelEventWait()
            calls.forEach { $0.cancel() }
        }
        var skills = skills
        while !isStopped {
            let message: WebSocketMessage
            do {
                message = try await withTimeout(timing.silence) { try await channel.receive() }
            } catch is TimedOut {
                log.warning(String(format: "heard nothing for %.0fs; reconnecting", timing.silence))
                return WebSocketClosed(reason: "the server went quiet")
            } catch {
                let closed = error as? WebSocketClosed ?? WebSocketClosed(reason: "the connection ended")
                log.info("connection ended: \(closed.code.map(String.init) ?? "") \(closed.reason)")
                return closed
            }
            guard case .text(let text) = message, let frame = try? DeviceProtocol.decode(text) else {
                continue  // a binary or broken frame: ignored, as the companion does
            }
            switch frame {
            case .call(let id, let tool, let args):
                // The server calls a tool only while its skill is on; this Mac checks too, so a
                // server bug, or a server it was tricked into pairing with, cannot use a skill
                // that is off here.
                if let skill = skillOf[tool], !skills.contains(skill) {
                    log.info("call \(tool) refused: its skill is off")
                    let refusal = DeviceProtocol.failure(id: id, error: "the \(skill) skill is off for Ira on this Mac")
                    try? await sender.send(DeviceProtocol.encodeResult(refusal))
                    continue
                }
                calls.removeAll { $0.isCancelled }
                calls.append(Task { [tools, log] in
                    // Every call is logged: its tool, how long, and how it ended. Never contents.
                    log.info("call \(tool) started")
                    let started = Date()
                    let reply: JSONValue
                    var outcome = "ok"
                    do {
                        let content = try await tools.call(tool, args: args)
                        reply = DeviceProtocol.result(id: id, content: content)
                    } catch let failure as ToolFailure {
                        outcome = "failed (\(DeviceClient.failureKind(failure.message)))"
                        reply = DeviceProtocol.failure(id: id, error: failure.message)
                    } catch {
                        outcome = "failed (\(type(of: error)))"
                        reply = DeviceProtocol.failure(id: id, error: error.localizedDescription)
                    }
                    log.info(String(format: "call %@ %@ in %.2fs", tool, outcome, Date().timeIntervalSince(started)))
                    do {
                        try await sender.send(DeviceProtocol.encodeResult(reply))
                    } catch {
                        log.warning("call \(tool): the answer could not be sent (the connection ended)")
                    }
                })
            case .ping:
                try? await sender.send(DeviceProtocol.pong.encoded())
            case .skills(let now):
                skills = now
                lock.locked { currentSkills = now }
                log.info("skills now \(now)")
                onState(.connected(deviceID: deviceID, skills: skills))
            case .drop(let change):
                onDrop(change)
            case .error(let reason):
                log.warning("the server said: \(reason)")
            case .welcome, .pong, .other:
                break
            }
        }
        return nil
    }

    /// A failure's kind for the log, from its message: never the message itself,
    /// which can name a file.
    static func failureKind(_ message: String) -> String {
        if message.contains("took too long") || message.contains("restarted") { return "late" }
        if message.contains("System Settings") || message.contains("is off for Ira") { return "permission" }
        if message.hasPrefix("Ira never") || message.contains("outside the folders") { return "refused" }
        if message.hasPrefix("unknown argument") || message.contains("must be") { return "arguments" }
        return "tool"
    }

    /// Tell the server this Mac is being removed: it revokes the token at once.
    /// Sent instead of a hello, as the companion's uninstaller does.
    public func sayGoodbye() async -> Bool {
        do {
            let channel = try await connector.connect(url: url, headers: headers)
            defer { channel.close(code: 1000) }
            try await channel.send(.text(DeviceProtocol.bye.encoded()))
            // The server closes the connection after revoking; wait a moment for that.
            _ = try? await withTimeout(3) { try await channel.receive() }
            return true
        } catch {
            return false
        }
    }
}

/// Sends frames one at a time, so concurrent results never interleave.
actor FrameSender {
    private let channel: WebSocketChannel

    init(channel: WebSocketChannel) {
        self.channel = channel
    }

    func send(_ text: String) async throws {
        try await channel.send(.text(text))
    }
}
