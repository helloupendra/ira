import Foundation

/// What the app remembers between launches, in UserDefaults. Never a token,
/// never what was said.
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
        static let conversationID = "conversationID"
        static let speakTypedReplies = "speakTypedReplies"
        static let setupDone = "setupDone"
        static let skillsAsked = "skillsAsked"
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

    /// This iPhone's name on the Devices page.
    public var deviceLabel: String {
        get { defaults.string(forKey: Key.deviceLabel) ?? "My iPhone" }
        set { defaults.set(newValue, forKey: Key.deviceLabel) }
    }

    /// The name the person gave their assistant.
    public var assistantName: String {
        get { defaults.string(forKey: Key.assistant) ?? "Ira" }
        set { defaults.set(newValue, forKey: Key.assistant) }
    }

    /// The conversation this iPhone continues: typing, calls and Siri all add to
    /// it, so "usko call karo" knows who "usko" is. New only when the person
    /// starts a new conversation.
    public var conversationID: String {
        if let id = defaults.string(forKey: Key.conversationID), ConversationID.isValid(id) { return id }
        let id = ConversationID.make()
        defaults.set(id, forKey: Key.conversationID)
        return id
    }

    /// Start a new conversation; returns its id.
    @discardableResult
    public func newConversation() -> String {
        let id = ConversationID.make()
        defaults.set(id, forKey: Key.conversationID)
        return id
    }

    /// The server gave the conversation another id (a new one it started).
    public func adoptConversation(_ id: String) {
        if ConversationID.isValid(id) { defaults.set(id, forKey: Key.conversationID) }
    }

    /// Speak answers to typed questions too (off: only answers to speech are spoken).
    public var speakTypedReplies: Bool {
        get { defaults.bool(forKey: Key.speakTypedReplies) }
        set { defaults.set(newValue, forKey: Key.speakTypedReplies) }
    }

    /// The person finished "Get Ira ready" once (it stays reachable in Settings).
    public var setupDone: Bool {
        get { defaults.bool(forKey: Key.setupDone) }
        set { defaults.set(newValue, forKey: Key.setupDone) }
    }

    /// Skills whose permission the app has asked iOS for, so a "no" shows
    /// "Open Settings" instead of asking again.
    public var skillsAsked: Set<String> {
        get { Set(defaults.stringArray(forKey: Key.skillsAsked) ?? []) }
        set { defaults.set(newValue.sorted(), forKey: Key.skillsAsked) }
    }

    /// Forget the server and this iPhone's name (the key is the Keychain's).
    public func forgetPairing() {
        for key in [Key.server, Key.deviceID, Key.deviceLabel, Key.assistant, Key.conversationID, Key.setupDone] {
            defaults.removeObject(forKey: key)
        }
    }
}

/// Conversation ids: what the server accepts, `^[A-Za-z0-9_-]{1,64}$`.
public enum ConversationID {
    public static func make() -> String {
        "ios-" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "").prefix(16)
    }

    public static func isValid(_ id: String) -> Bool {
        id.range(of: #"^[A-Za-z0-9_-]{1,64}$"#, options: .regularExpression) != nil
    }
}
