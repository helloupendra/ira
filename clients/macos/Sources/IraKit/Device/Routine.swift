import CoreGraphics
import CryptoKit
import Foundation

/// The routine skill: when this Mac locks, sleeps and wakes, its first activity
/// of the day, and which network it is on (docs/learning.md).
///
/// Only while the person switched the `routine` skill on for this Mac. Every 30
/// seconds it reads:
///
/// * the screen lock, from the console session (`CGSSessionScreenIsLocked`);
/// * sleep and wake: the wall clock moves on while the Mac sleeps and the
///   monotonic clock does not, so a gap between them is a sleep;
/// * how long since the last keyboard or mouse input, for the first activity of
///   the day;
/// * the network, as a hash of the default gateway's hardware address with a
///   salt kept on this Mac. Neither the network's name nor its addresses leave
///   the Mac; the person names the network on their Ira page instead.
///
/// It never reads what is on the screen, which apps run, or anything in a file.
/// The frames and the fingerprint are the Python companion's, so networks a
/// person already named keep their names when the app takes over its salt.
public final class Routine: @unchecked Sendable {
    public static let interval: Double = 30
    static let sleepGap: Double = 90
    static let activeIdle: Double = 120

    public protocol Probe: Sendable {
        func locked() -> Bool?
        func idle() -> Double?
        /// (gateway address, its hardware address), or nil when offline.
        func network() -> (gateway: String, hardware: String)?
    }

    private let send: @Sendable (JSONValue) -> Void
    private let probe: Probe
    private let salt: String
    private let clock: @Sendable () -> Double
    private let mono: @Sendable () -> Double
    private let lock = NSLock()
    private var wall: Double?
    private var monoAt: Double?
    private var wasLocked: Bool?
    private var network: String?
    private var seenNetwork = false
    private var activeDay: String?

    public init(
        salt: String, probe: Probe = MacProbe(),
        clock: @escaping @Sendable () -> Double = { Date().timeIntervalSince1970 },
        mono: @escaping @Sendable () -> Double = { ProcessInfo.processInfo.systemUptime },
        send: @escaping @Sendable (JSONValue) -> Void
    ) {
        self.salt = salt
        self.probe = probe
        self.clock = clock
        self.mono = mono
        self.send = send
    }

    /// Forget the last reading (the skill went off): the next one starts afresh.
    public func reset() {
        lock.locked {
            wall = nil
            monoAt = nil
            wasLocked = nil
            network = nil
            seenNetwork = false
        }
    }

    /// A network's identity: salted, so the server can only tell networks apart.
    public static func fingerprint(salt: String, gateway: String, hardware: String) -> String {
        let digest = SHA256.hash(data: Data("\(salt)|\(gateway)|\(hardware)".utf8))
        return String(digest.map { String(format: "%02x", $0) }.joined().prefix(24))
    }

    static func day(_ seconds: Double) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter.string(from: Date(timeIntervalSince1970: seconds))
    }

    /// Read once; returns the observations sent.
    @discardableResult
    public func tick() -> [JSONValue] {
        let now = clock(), monoNow = mono()
        let reading = probe.network()
        let locked = probe.locked()
        let idle = probe.idle()
        return lock.locked {
            var sent: [JSONValue] = []
            func emit(_ kind: String, _ at: Double) {
                let frame: JSONValue = [
                    "type": "observe", "kind": .string(kind), "at": .number((at * 1000).rounded() / 1000),
                    "network": network.map { .string($0) } ?? .null,
                ]
                send(frame)
                sent.append(frame)
            }
            if let wall, let monoAt {
                let gap = (now - wall) - (monoNow - monoAt)
                if gap > Routine.sleepGap {
                    emit("sleep", wall)
                    emit("wake", now)
                }
            }
            wall = now
            monoAt = monoNow

            let current = reading.map { Routine.fingerprint(salt: salt, gateway: $0.gateway, hardware: $0.hardware) }
            if current != network || !seenNetwork {
                network = current
                seenNetwork = true
                if current != nil { emit("network", now) }
            }

            if let locked, let before = wasLocked, locked != before {
                emit(locked ? "lock" : "unlock", now)
            }
            if let locked { wasLocked = locked }

            let today = Routine.day(now)
            if let idle, idle < Routine.activeIdle, locked != true, activeDay != today {
                activeDay = today
                emit("first_activity", now - idle)
            }
            return sent
        }
    }

    // MARK: Reading the Mac

    static let gatewayPattern = try! NSRegularExpression(pattern: #"^\s*gateway:\s*(\S+)"#, options: .anchorsMatchLines)
    static let hardwarePattern = try! NSRegularExpression(
        pattern: #"\bat\s+([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})\b"#, options: .caseInsensitive)

    public static func parseGateway(_ text: String) -> String? {
        guard let match = gatewayPattern.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
            let range = Range(match.range(at: 1), in: text)
        else { return nil }
        return String(text[range])
    }

    public static func parseHardware(_ text: String) -> String? {
        guard let match = hardwarePattern.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
            let range = Range(match.range(at: 1), in: text)
        else { return nil }
        return text[range].lowercased().split(separator: ":").map { $0.count == 1 ? "0" + $0 : String($0) }.joined(separator: ":")
    }

    /// Reads the real Mac with what macOS ships.
    public struct MacProbe: Probe {
        public init() {}

        public func locked() -> Bool? {
            guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return nil }
            return (session["CGSSessionScreenIsLocked"] as? Bool) ?? false
        }

        public func idle() -> Double? {
            guard let any = CGEventType(rawValue: ~0) else { return nil }
            return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: any)
        }

        public func network() -> (gateway: String, hardware: String)? {
            guard let gateway = Routine.parseGateway(MacProbe.run(["/sbin/route", "-n", "get", "default"])),
                let hardware = Routine.parseHardware(MacProbe.run(["/usr/sbin/arp", "-n", gateway]))
            else { return nil }
            return (gateway, hardware)
        }

        static func run(_ argv: [String]) -> String {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: argv[0])
            process.arguments = Array(argv.dropFirst())
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = FileHandle.nullDevice
            do { try process.run() } catch { return "" }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return String(decoding: data, as: UTF8.self)
        }
    }
}
