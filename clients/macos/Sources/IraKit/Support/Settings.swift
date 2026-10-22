import Foundation
import Security

/// What the app remembers between launches, in UserDefaults. Never a token.
public final class AppSettings: @unchecked Sendable {
    public let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    private enum Key {
        static let server = "server"
        static let deviceID = "deviceID"
        static let deviceLabel = "deviceLabel"
        static let assistant = "assistantName"
        static let hotKeyCode = "hotKeyCode"
        static let hotKeyModifiers = "hotKeyModifiers"
        static let extraFolders = "extraFolders"
        static let onlyFolders = "onlyFolders"
        static let speakReplies = "speakReplies"
        static let firstRunDone = "firstRunDone"
        static let conversationID = "conversationID"
        static let conversationAt = "conversationAt"
        static let signedInEmail = "signedInEmail"
        static let networkSalt = "networkSalt"
        static let wakeWord = "wakeWord"
    }

    /// Salts this Mac's network codes (the routine skill), so the server can only
    /// tell networks apart. Made once; taken over from the old companion if it had one.
    public var networkSalt: String {
        get {
            if let salt = defaults.string(forKey: Key.networkSalt), !salt.isEmpty { return salt }
            var bytes = [UInt8](repeating: 0, count: 16)
            _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
            let salt = bytes.map { String(format: "%02x", $0) }.joined()
            defaults.set(salt, forKey: Key.networkSalt)
            return salt
        }
        set { defaults.set(newValue, forKey: Key.networkSalt) }
    }

    /// "Hey Ira": off until the person switches it on.
    public var wakeWord: Bool {
        get { defaults.bool(forKey: Key.wakeWord) }
        set { defaults.set(newValue, forKey: Key.wakeWord) }
    }

    /// The paired server, e.g. `https://ira.example.com`. Empty until paired.
    public var server: String {
        get { defaults.string(forKey: Key.server) ?? "" }
        set { defaults.set(newValue, forKey: Key.server) }
    }

    public var deviceID: Int? {
        get { defaults.object(forKey: Key.deviceID) as? Int }
        set { defaults.set(newValue, forKey: Key.deviceID) }
    }

    public var deviceLabel: String {
        get { defaults.string(forKey: Key.deviceLabel) ?? "My Mac" }
        set { defaults.set(newValue, forKey: Key.deviceLabel) }
    }

    public var assistantName: String {
        get { defaults.string(forKey: Key.assistant) ?? "Ira" }
        set { defaults.set(newValue, forKey: Key.assistant) }
    }

    /// The global hotkey as a virtual key code and Carbon modifier flags.
    /// Default: Option-Space (key 49, optionKey 0x0800).
    public var hotKeyCode: UInt32 {
        get { (defaults.object(forKey: Key.hotKeyCode) as? NSNumber)?.uint32Value ?? 49 }
        set { defaults.set(NSNumber(value: newValue), forKey: Key.hotKeyCode) }
    }

    public var hotKeyModifiers: UInt32 {
        get { (defaults.object(forKey: Key.hotKeyModifiers) as? NSNumber)?.uint32Value ?? 0x0800 }
        set { defaults.set(NSNumber(value: newValue), forKey: Key.hotKeyModifiers) }
    }

    /// Folders outside the home folder that Ira may also search and read.
    public var extraFolders: [String] {
        get { defaults.stringArray(forKey: Key.extraFolders) ?? [] }
        set { defaults.set(newValue, forKey: Key.extraFolders) }
    }

    /// When not empty, Ira searches and reads only inside these folders.
    public var onlyFolders: [String] {
        get { defaults.stringArray(forKey: Key.onlyFolders) ?? [] }
        set { defaults.set(newValue, forKey: Key.onlyFolders) }
    }

    public var speakReplies: Bool {
        get { defaults.object(forKey: Key.speakReplies) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.speakReplies) }
    }

    public var firstRunDone: Bool {
        get { defaults.bool(forKey: Key.firstRunDone) }
        set { defaults.set(newValue, forKey: Key.firstRunDone) }
    }

    /// The email of the account signed in for typing without live voice (shown, never a secret).
    public var signedInEmail: String? {
        get { defaults.string(forKey: Key.signedInEmail) }
        set { defaults.set(newValue, forKey: Key.signedInEmail) }
    }

    /// The conversation to continue, if it was used in the last 30 minutes.
    public func recentConversation(now: Date = Date()) -> String? {
        guard let id = defaults.string(forKey: Key.conversationID),
            let at = defaults.object(forKey: Key.conversationAt) as? Date,
            now.timeIntervalSince(at) < 30 * 60
        else { return nil }
        return id
    }

    public func rememberConversation(_ id: String?, now: Date = Date()) {
        defaults.set(id, forKey: Key.conversationID)
        defaults.set(now, forKey: Key.conversationAt)
    }

    /// Forget the pairing (the token is deleted from the Keychain separately).
    public func forgetPairing() {
        for key in [Key.server, Key.deviceID, Key.deviceLabel, Key.conversationID, Key.conversationAt, Key.signedInEmail] {
            defaults.removeObject(forKey: key)
        }
    }
}
