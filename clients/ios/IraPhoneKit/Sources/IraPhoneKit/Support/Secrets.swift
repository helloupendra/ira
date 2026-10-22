import Foundation
import Security

/// What reading a secret found. A read that fails (the iPhone was restarted and
/// not unlocked yet, a Keychain error) is not the same as no secret, and must
/// never be taken for "not paired".
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
    /// This iPhone's device token (`irad_...`), from pairing.
    public static let device = "device"
}

public struct SecretError: LocalizedError {
    public let message: String
    public var errorDescription: String? { message }
}

/// The iPhone's Keychain. The token is readable only on this iPhone (it is never
/// in a backup restored to another phone, nor synced through iCloud), and only
/// after the phone has been unlocked once since it started, so a call or a Siri
/// request can still use it while the phone is locked.
public struct KeychainStore: SecretStore {
    public let service: String

    public init(service: String = IraPhone.bundleID) {
        self.service = service
    }

    /// The protection every item gets.
    public static let accessible = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String

    func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    /// The attributes a new item is added with: this device only, after first unlock,
    /// never synchronized.
    func addQuery(_ account: String, data: Data) -> [String: Any] {
        var add = query(account)
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = KeychainStore.accessible
        add[kSecAttrSynchronizable as String] = kCFBooleanFalse
        add[kSecAttrLabel as String] = "Ira for iPhone (\(account))"
        return add
    }

    public func read(_ account: String) -> SecretRead {
        var query = query(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        switch status {
        case errSecSuccess:
            guard let data = item as? Data, let text = String(data: data, encoding: .utf8) else {
                return .failed(status)
            }
            return .found(text)
        case errSecItemNotFound:
            return .missing
        default:
            // errSecInteractionNotAllowed: the phone has not been unlocked since it started.
            return .failed(status)
        }
    }

    public func save(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let update: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: KeychainStore.accessible,
        ]
        var status = SecItemUpdate(query(account) as CFDictionary, update as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(addQuery(account, data: data) as CFDictionary, nil)
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
    private var failures: [String: Int32] = [:]
    private var deleted: [String] = []
    private let lock = NSLock()

    public init(_ values: [String: String] = [:]) {
        self.values = values
    }

    /// Make reads of `account` fail with `status`, as a locked Keychain would.
    public func fail(_ account: String, status: Int32?) {
        lock.withLock { failures[account] = status }
    }

    public var deletions: [String] { lock.withLock { deleted } }

    public func read(_ account: String) -> SecretRead {
        lock.withLock {
            if let status = failures[account] { return .failed(status) }
            return values[account].map { .found($0) } ?? .missing
        }
    }

    public func save(_ value: String, account: String) throws {
        lock.withLock { values[account] = value }
    }

    @discardableResult
    public func delete(_ account: String) -> Bool {
        lock.withLock {
            values[account] = nil
            deleted.append(account)
        }
        return true
    }
}

/// This iPhone's pairing: the server in the settings and the key in the Keychain.
///
/// Two rules, tested: a key that cannot be read is never "not paired" (the app
/// says the phone must be unlocked and tries again), and nothing here deletes
/// the key or forgets the server except `removeOnPurpose`, which only the
/// person's "Remove this iPhone from Ira" calls. Pairing again overwrites the key.
public struct PairingRecord: Sendable {
    public enum Status: Equatable, Sendable {
        case unpaired
        case paired
        /// The Keychain did not hand over the key. Try again later; never unpair.
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

    /// The token, when it can be read now.
    public var token: String? { secrets.load(SecretAccount.device) }

    /// A new pairing: the key is replaced (never deleted first), with its server.
    public func adopt(_ paired: Pairing.Paired) throws {
        guard TokenShape.isDeviceToken(paired.token) else {
            throw SecretError(message: "the server's answer did not hold a device token")
        }
        try secrets.save(paired.token, account: SecretAccount.device)
        settings.server = paired.server
        settings.deviceID = paired.deviceID
        settings.deviceLabel = paired.label
        if let assistant = paired.assistant, !assistant.isEmpty { settings.assistantName = assistant }
    }

    /// The person chose "Remove this iPhone from Ira": forget the key and the server.
    public func removeOnPurpose() {
        secrets.delete(SecretAccount.device)
        settings.forgetPairing()
    }

    /// The sentence the app shows for an unreadable key.
    public static let unreadable =
        "Ira can't read its key yet. Unlock your iPhone, then open Ira again. You do not need to pair again."
}

public enum TokenShape {
    /// What a device token looks like; anything else is never stored.
    public static func isDeviceToken(_ text: String) -> Bool {
        text.range(of: #"^irad_[A-Za-z0-9_-]{20,100}$"#, options: .regularExpression) != nil
    }
}
