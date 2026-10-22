import Foundation
import Security

/// Where the app keeps its secrets: the device token and, if the person signed
/// in for typing, their session token. Never in a file, UserDefaults or a log.
public protocol SecretStore: Sendable {
    func load(_ account: String) -> String?
    func save(_ value: String, account: String) throws
    @discardableResult func delete(_ account: String) -> Bool
}

public enum SecretAccount {
    /// This Mac's device token (`irad_...`), from pairing.
    public static let device = "device"
    /// A session token (`ira_s_...`) from signing in, used only when live voice is not available.
    public static let session = "session"
}

public struct SecretError: LocalizedError {
    public let message: String
    public var errorDescription: String? { message }
}

/// The login Keychain, service `in.ira.mac`.
public struct KeychainStore: SecretStore {
    public let service: String

    public init(service: String = "in.ira.mac") {
        self.service = service
    }

    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    public func load(_ account: String) -> String? {
        var query = query(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
            let data = item as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
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

    public func load(_ account: String) -> String? {
        lock.lock()
        defer { lock.unlock() }
        return values[account]
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
        return true
    }
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
