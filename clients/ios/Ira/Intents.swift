import AppIntents
import IraPhoneKit

/// "Hey Siri, Ask Ira": Siri asks what you want to ask, sends it to your Ira with
/// this iPhone's own key, and says the answer. No Shortcut to build.
struct AskIraIntent: AppIntent {
    static let title: LocalizedStringResource = "Ask Ira"
    static let description = IntentDescription("Ask your own Ira a question and hear the answer.")
    static let openAppWhenRun = false

    @Parameter(title: "Question", requestValueDialog: IntentDialog("What do you want to ask Ira?"))
    var question: String

    func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
        let said = try await SiriAsk.answer(question) { summary in
            try await requestConfirmation(result: .result(dialog: "\(summary). Shall I?"), confirmationActionName: .go)
        }
        return .result(value: said, dialog: "\(said)")
    }
}

/// "Hey Siri, Tell Ira": for what you tell Ira rather than ask ("Rahul is my CA",
/// "remind me at 6 to call the bank"). Ira says what it saved.
struct TellIraIntent: AppIntent {
    static let title: LocalizedStringResource = "Tell Ira"
    static let description = IntentDescription("Tell your own Ira something to remember, or a reminder to keep.")
    static let openAppWhenRun = false

    @Parameter(title: "What to tell Ira", requestValueDialog: IntentDialog("What should I tell Ira?"))
    var note: String

    func perform() async throws -> some IntentResult & ProvidesDialog & ReturnsValue<String> {
        let said = try await SiriAsk.answer(note) { summary in
            try await requestConfirmation(result: .result(dialog: "\(summary). Shall I?"), confirmationActionName: .go)
        }
        return .result(value: said, dialog: "\(said)")
    }
}

/// "Hey Siri, Talk to Ira": opens Ira and starts a call.
struct TalkToIraIntent: AppIntent {
    static let title: LocalizedStringResource = "Talk to Ira"
    static let description = IntentDescription("Open Ira and start a call: just talk, and Ira answers aloud.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppModel.shared.requestCall()
        return .result()
    }
}

struct IraShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskIraIntent(),
            phrases: ["Ask \(.applicationName)", "Ask \(.applicationName) something", "Ask \(.applicationName) a question"],
            shortTitle: "Ask Ira",
            systemImageName: "bubble.left.and.text.bubble.right")
        AppShortcut(
            intent: TellIraIntent(),
            phrases: ["Tell \(.applicationName)", "Tell \(.applicationName) something", "Note this in \(.applicationName)"],
            shortTitle: "Tell Ira",
            systemImageName: "square.and.pencil")
        AppShortcut(
            intent: TalkToIraIntent(),
            phrases: ["Talk to \(.applicationName)", "Start talking to \(.applicationName)", "Start a call with \(.applicationName)"],
            shortTitle: "Talk to Ira",
            systemImageName: "phone")
    }
}

/// What Siri says when Ira cannot answer.
struct IraIntentError: Error, CustomLocalizedStringResourceConvertible {
    let message: String
    var localizedStringResource: LocalizedStringResource { "\(message)" }
}

/// Asking for Siri: the same conversation as the app (so "usko call karo" knows
/// who), with this iPhone's key. A Tier 2 proposal is read back and Siri asks
/// yes or no; a Tier 3 one needs the PIN, typed in the app, never spoken.
enum SiriAsk {
    /// Ask, and when Ira proposes a Tier 2 action, let Siri ask yes or no
    /// (`confirm` throws for a no). Returns what Siri says.
    static func answer(_ text: String, confirm: (String) async throws -> Void) async throws -> String {
        let (client, answer) = try await ask(text)
        guard let card = answer.action else {
            return answer.text.isEmpty ? "Ira had no answer. Try asking another way." : answer.text
        }
        switch card.need {
        case .yes:
            do {
                try await confirm(card.summary)
            } catch {
                _ = try? await client.cancel(actionID: card.id)
                return "Cancelled. Nothing was done."
            }
            do {
                return try await client.approve(actionID: card.id).sentence
            } catch let failure as AskClient.Failure {
                throw IraIntentError(message: failure.message)
            }
        case .pin:
            return "\(card.summary). This needs your PIN: open Ira and type it there, within two minutes."
        case .cannot(let why):
            return "\(card.summary). \(why)"
        case .settled:
            return answer.text
        }
    }

    static func ask(_ text: String) async throws -> (AskClient, Answer) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw IraIntentError(message: "I didn't catch that. Ask again.") }
        let settings = AppSettings()
        let record = PairingRecord(settings: settings, secrets: KeychainStore())
        switch record.status {
        case .unpaired:
            throw IraIntentError(message: "This iPhone is not paired with your Ira yet. Open Ira to pair it.")
        case .keyUnreadable:
            throw IraIntentError(message: "Unlock your iPhone, then ask again.")
        case .paired:
            break
        }
        let client = AskClient(server: settings.server, token: { record.token })
        do {
            let answer = try await client.ask(text, conversationID: settings.conversationID)
            if let id = answer.conversationID { settings.adoptConversation(id) }
            return (client, answer)
        } catch let failure as AskClient.Failure {
            throw IraIntentError(message: failure.message)
        }
    }
}
