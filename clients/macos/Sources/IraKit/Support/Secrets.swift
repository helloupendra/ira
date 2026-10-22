import Foundation
import Security

/// What reading a secret found. A read that fails (the Keychain locked, a
/// prompt refused, an item another build of Ira made) is not the same as no
/// secret, and must never be taken for "not paired".
public enum SecretRead: Equatable, Sendable {
    case found(String)
    case missing
    case failed(Int32)
}

/// Where the app keeps its secret: the device token. Never in a file,
/// UserDefaults or a log.
public protocol SecretStore: Sendable {
    func read(_ account: String) -> SecretRead
    func save(_ value: String, account: String) throws
    @discardableResult func delete(_ account: String) -> Bool
}

extension SecretStore {
    /// The secret, or nil when it is missing or cannot be read.
    public func load(_ account: String) -> String? {
        if case .found(let value) = read(account) { return value }
        return nil
    }
}

public enum SecretAccount {
    /// This Mac's device token (`irad_...`), from pairing.
    public static let device = "device"
}

public struct SecretError: LocalizedError {
    public let message: String
    public var errorDescription: String? { message }
}

/// The login Keychain, service `in.ira.mac` (a test build with another bundle
/// id, such as `in.ira.mac.test`, keeps its own).
public struct KeychainStore: SecretStore {
    public let service: String
    /// Fail instead of asking (for scripted checks): a read that would show
    /// macOS's "Ira wants to use your confidential information" answers `failed`.
    public let interactive: Bool

    public static var defaultService: String {
        let id = Bundle.main.bundleIdentifier ?? ""
        return id.hasPrefix("in.ira.mac") ? id : "in.ira.mac"
    }

    public init(service: String = KeychainStore.defaultService,
                interactive: Bool = ProcessInfo.processInfo.environment["IRA_KEYCHAIN_NO_UI"] == nil) {
        self.service = service
        self.interactive = interactive
    }

    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    public func read(_ account: String) -> SecretRead {
        var query = query(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        if !interactive {
            query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail
            SecKeychainSetUserInteractionAllowed(false)
        }
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        switch status {
        case errSecSuccess:
            guard let data = item as? Data, let text = String(data: data, encoding: .utf8) else { return .failed(status) }
            return .found(text)
        case errSecItemNotFound:
            return .missing
        default:
            return .failed(status)
        }
    }

    public func save(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let update: [String: Any] = [kSecValueData as String: data]
        var status = SecItemUpdate(query(account) as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            var add = query(account)
            add[kSecValueData as String] = data
            add[kSecAttrLabel as String] = "Ira for Mac (\(account))"
            add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(add as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw SecretError(message: "the Keychain did not keep it (error \(status))")
        }
    }

    @discardableResult
    public func delete(_ account: String) -> Bool {
        let status = SecItemDelete(query(account) as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}

/// Secrets in memory only: for tests and previews.
public final class MemorySecretStore: SecretStore, @unchecked Sendable {
    private var values: [String: String] = [:]
    private let lock = NSLock()

    public init(_ values: [String: String] = [:]) {
        self.values = values
    }

    /// Accounts whose reads fail, as a refused Keychain prompt would.
    public var failing: [String: Int32] = [:]
    public private(set) var deletions: [String] = []

    public func read(_ account: String) -> SecretRead {
        lock.lock()
        defer { lock.unlock() }
        if let status = failing[account] { return .failed(status) }
        return values[account].map { .found($0) } ?? .missing
    }

    public func save(_ value: String, account: String) throws {
        lock.lock()
        defer { lock.unlock() }
        values[account] = value
    }

    @discardableResult
    public func delete(_ account: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        values[account] = nil
        deletions.append(account)
        return true
    }
}

/// This Mac's pairing: the server in the settings and the key in the Keychain.
///
/// Two rules, tested: a key that cannot be read is never "not paired" (the
/// app asks for the Keychain instead), and nothing here deletes the key or
/// forgets the server except `removeOnPurpose`, which only the person's
/// "Remove Ira from this Mac" calls. Pairing again overwrites the key.
public struct PairingRecord: Sendable {
    public enum Status: Equatable, Sendable {
        case unpaired
        case paired
        /// The Keychain did not hand over the key (a refused prompt, a locked
        /// Keychain, another build of Ira). Ask again; never unpair.
        case keyUnreadable(Int32)
    }

    public let settings: AppSettings
    public let secrets: SecretStore

    public init(settings: AppSettings, secrets: SecretStore) {
        self.settings = settings
        self.secrets = secrets
    }

    public var status: Status {
        switch secrets.read(SecretAccount.device) {
        case .found: return settings.server.isEmpty ? .unpaired : .paired
        case .missing: return .unpaired
        case .failed(let code): return settings.server.isEmpty ? .unpaired : .keyUnreadable(code)
        }
    }

    /// A new pairing: the key is replaced (never deleted first), with its server.
    public func adopt(server: String, token: String, deviceID: Int?, label: String) throws {
        try secrets.save(token, account: SecretAccount.device)
        settings.server = server
        settings.deviceID = deviceID
        settings.deviceLabel = label
    }

    /// The person chose "Remove Ira from this Mac": forget the key and the server.
    public func removeOnPurpose() {
        secrets.delete(SecretAccount.device)
        secrets.delete("session")  // left by 0.1.0's sign-in, if any
        settings.forgetPairing()
        settings.firstRunDone = false
    }

    /// The sentence the app shows for an unreadable key.
    public static let unreadable =
        "Ira can't read its key in the Keychain. Choose Always Allow when macOS asks, or pair again."
}

public enum TokenShape {
    /// What a device token looks like; anything else is never stored.
    public static func isDeviceToken(_ text: String) -> Bool {
        text.range(of: #"^irad_[A-Za-z0-9_-]{20,100}$"#, options: .regularExpression) != nil
    }

    public static func isSessionToken(_ text: String) -> Bool {
        text.range(of: #"^ira_s_[A-Za-z0-9_-]{20,100}$"#, options: .regularExpression) != nil
    }
}
