import Foundation

/// The old Python companion (`clients/mac`, retired): finding it, taking over its
/// pairing, and removing it, as its `uninstall.sh` did.
///
/// The companion lived in `~/Library/Application Support/ira-mac`, ran from the
/// LaunchAgent `in.ira.mac`, and kept its token in the Keychain under service
/// `ira-mac`, account `device`. Ira for Mac keeps its own under service
/// `in.ira.mac`, so the two never share a Keychain item. The LaunchAgent's
/// label and the app's bundle id are the same string, but launchd labels and
/// bundle ids are separate names; once the agent is removed nothing else uses
/// the label.
public struct Companion: Sendable {
    public static let label = "in.ira.mac"
    public static let keychainService = "ira-mac"

    public typealias Runner = @Sendable ([String]) async -> Command.Result?

    public let home: URL
    /// Runs a system command (`launchctl`, `security`); tests pass a recorder.
    let run: Runner

    public init(
        home: URL = FileManager.default.homeDirectoryForCurrentUser,
        run: @escaping Runner = { try? await Command.run($0, timeout: 15) }
    ) {
        self.home = home
        self.run = run
    }

    public var folder: URL { home.appendingPathComponent("Library/Application Support/ira-mac") }
    public var agent: URL { home.appendingPathComponent("Library/LaunchAgents/\(Companion.label).plist") }
    public var nativeHosts: [URL] {
        ["Google/Chrome", "Google/Chrome Beta", "Chromium", "BraveSoftware/Brave-Browser", "Microsoft Edge"].map {
            home.appendingPathComponent("Library/Application Support/\($0)/NativeMessagingHosts/\(Companion.label).json")
        }
    }

    /// What the companion knew: its server, device and network salt. Never its token.
    public struct Found: Equatable, Sendable {
        public let server: String
        public let deviceID: Int?
        public let label: String
        public let networkSalt: String
        /// The companion's tasks settings, if it had any (the app keeps them in tasks.json).
        public let tasks: JSONValue?

        public init(server: String, deviceID: Int?, label: String, networkSalt: String, tasks: JSONValue?) {
            self.server = server
            self.deviceID = deviceID
            self.label = label
            self.networkSalt = networkSalt
            self.tasks = tasks
        }
    }

    /// Whether any part of the companion is still on this Mac.
    public var present: Bool {
        let manager = FileManager.default
        return manager.fileExists(atPath: folder.path) || manager.fileExists(atPath: agent.path)
            || nativeHosts.contains { manager.fileExists(atPath: $0.path) }
    }

    /// The companion's settings, from its config.json.
    public func settings() -> Found? {
        guard let data = try? Data(contentsOf: folder.appendingPathComponent("config.json")) else { return nil }
        return Companion.parse(data)
    }

    public static func parse(_ data: Data) -> Found? {
        guard let config = JSONValue.parse(data), config.objectValue != nil else { return nil }
        let server = config["server"]?.stringValue ?? ""
        var tasks: JSONValue?
        if let value = config["tasks"], value.objectValue?.isEmpty == false { tasks = value }
        return Found(
            server: server, deviceID: config["device_id"]?.intValue,
            label: config["label"]?.stringValue ?? "My Mac",
            networkSalt: config["network_salt"]?.stringValue ?? "", tasks: tasks)
    }

    /// The companion's token, read with the same `security` tool that saved it
    /// (so macOS does not ask again). Nil if there is none.
    public func token() async -> String? {
        guard let result = await run(
            ["/usr/bin/security", "find-generic-password", "-s", Companion.keychainService, "-a", "device", "-w"])
        else { return nil }
        let token = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        return result.status == 0 && TokenShape.isDeviceToken(token) ? token : nil
    }

    /// Stop the companion and remove every part of it from this Mac: the
    /// LaunchAgent, the Chrome host manifests, its Keychain item and its folder.
    /// The extension itself is removed in chrome://extensions by the person.
    public func remove() async {
        _ = await run(["/bin/launchctl", "bootout", "gui/\(getuid())/\(Companion.label)"])
        let manager = FileManager.default
        try? manager.removeItem(at: agent)
        for host in nativeHosts { try? manager.removeItem(at: host) }
        _ = await run(["/usr/bin/security", "delete-generic-password", "-s", Companion.keychainService, "-a", "device"])
        try? manager.removeItem(at: folder)
    }
}
