import Foundation

/// "Get Ira ready": pair, the microphone, speech recognition, then each skill's
/// permission, each with one line on why and what to press.
public struct ChecklistRow: Equatable, Sendable, Identifiable {
    public enum Action: Equatable, Sendable {
        /// Nothing to do.
        case done
        /// Pair this iPhone.
        case pair
        /// iOS may still ask: show its prompt.
        case allow
        /// iOS stopped asking (a no, or not enough): only Settings can change it.
        case openSettings(String)
        /// Nothing the person can change here.
        case unavailable(String)
    }

    public let item: ChecklistItem
    public let title: String
    public let reason: String
    public let action: Action
    /// Talking needs it; the rest are for skills the person may never use.
    public let required: Bool

    public var id: String { item.id }
}

public enum Checklist {
    public static func title(_ item: ChecklistItem) -> String {
        switch item {
        case .pair: return "Pair with your Ira"
        case .microphone: return "Microphone"
        case .speech: return "Speech recognition"
        case .skill(let skill): return skill.title
        }
    }

    public static func reason(_ item: ChecklistItem) -> String {
        switch item {
        case .pair: return "So this iPhone knows which Ira is yours. Once, with a code from Your devices."
        case .microphone: return "So you can talk to Ira. It listens only during a call you start."
        case .speech: return "So the iPhone can turn your words into text when your Ira has no live calls."
        case .skill(let skill): return skill.reason
        }
    }

    public static func row(_ item: ChecklistItem, paired: Bool, state: PermissionState) -> ChecklistRow {
        let action: ChecklistRow.Action
        if item == .pair {
            action = paired ? .done : .pair
        } else {
            switch state {
            case .allowed: action = .done
            case .notAsked: action = .allow
            case .denied:
                action = .openSettings("You said no before, so iOS will not ask again. Switch it on in Settings.")
            case .partial(let why): action = .openSettings(why)
            case .restricted: action = .unavailable("Screen Time or a profile on this iPhone does not allow it.")
            }
        }
        return ChecklistRow(
            item: item, title: title(item), reason: reason(item), action: action,
            required: item == .pair || item == .microphone)
    }

    public static func rows(paired: Bool, states: (ChecklistItem) -> PermissionState) -> [ChecklistRow] {
        ChecklistItem.all.map { row($0, paired: paired, state: states($0)) }
    }

    /// Ready to talk: paired, and the microphone allowed. Typing needs only pairing.
    public static func ready(_ rows: [ChecklistRow]) -> Bool {
        rows.filter(\.required).allSatisfy { $0.action == .done }
    }
}

/// What Ira is doing, in words for the busy line: "Checking your calendar…".
public enum StepWords {
    public static let connecting = "Connecting to your Ira…"
    public static let thinking = "Thinking…"
    public static let listening = "Listening…"
    public static let speaking = "Speaking…"
    public static let pairing = "Pairing with your Ira…"

    public static func tool(_ name: String) -> String {
        switch name {
        case "contacts_lookup": return "Looking in your contacts…"
        case "calendar_read", "calendar_add": return "Checking your calendar…"
        case "reminders_list", "reminders_add", "reminders_done": return "Checking your reminders…"
        case "location_now": return "Finding where you are…"
        case "call_place": return "Getting the call ready…"
        case "web_search", "news_search": return "Searching the web…"
        default:
            let words = name.replacingOccurrences(of: "_", with: " ")
            return words.isEmpty ? "Working…" : "Using \(words)…"
        }
    }
}

/// Errors in plain words, each with what to do next.
public enum Plain {
    /// A server's or a tool's message as a sentence that ends with a next step.
    public static func sentence(_ message: String) -> String {
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return "Something went wrong on your Ira. Try again." }
        let sentence = text.prefix(1).uppercased() + text.dropFirst()
        if sentence.hasSuffix(".") || sentence.hasSuffix("?") || sentence.hasSuffix("!") { return sentence }
        return sentence + ". Try again, or ask another way."
    }

    /// What the device connection's state means for the person.
    public static func device(_ state: DeviceState) -> String? {
        switch state {
        case .connected, .connecting, .stopped: return nil
        case .waiting(let seconds, _):
            return "This iPhone's tools are offline; trying again in \(Int(seconds.rounded())) s. Typing still works."
        case .refused:
            return "Your Ira no longer knows this iPhone (it was removed on Your devices). Pair it again in Settings."
        case .keyUnavailable:
            return PairingRecord.unreadable
        }
    }
}
