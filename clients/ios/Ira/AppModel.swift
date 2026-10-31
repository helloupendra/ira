import IraPhoneKit
import Observation
import SwiftUI
import UIKit

/// The app's state: this iPhone's pairing, its device connection (the tools Ira
/// may use here), the server's abilities, and the first-run checklist.
@MainActor
@Observable
final class AppModel {
    static let shared = AppModel()

    let settings = AppSettings()
    let secrets: SecretStore = KeychainStore()
    let eventKit = EventKitTools()
    let permissions: SystemPermissions
    let talk: TalkController
    /// The person's Drop, shared by their devices.
    let drop = DropBox()

    /// Paired, not paired, or a key iOS will not hand over yet.
    private(set) var pairing: PairingRecord.Status = .unpaired
    /// What the server can do for this person, once asked.
    private(set) var info: ServerInfo?
    private(set) var deviceState: DeviceState = .stopped
    private(set) var skillsOn: [String] = []
    /// What the app is doing now, for the busy line ("Pairing with your Ira…").
    private(set) var busy: String?
    /// A problem, in plain words, with what to do next.
    var notice: String?
    private(set) var activity: [Activity] = []
    /// Bumped when iOS may have changed a permission, so the checklist reads them again.
    private(set) var permissionsChecked = Date()
    /// Show "Get Ira ready" (first run, or chosen in Settings).
    var showingSetup = false
    /// A Siri request to start a call, waiting for the app to be on screen.
    var callRequested = false
    /// A pairing link opened from outside, waiting for the person's yes.
    var linkToConfirm: LinkPair?

    @ObservationIgnored private var device: DeviceClient?
    private(set) var foreground = true

    var record: PairingRecord { PairingRecord(settings: settings, secrets: secrets) }
    var assistantName: String { info?.name ?? settings.assistantName }

    private init() {
        permissions = SystemPermissions(eventKit: eventKit)
        talk = TalkController(settings: settings)
        pairing = record.status
        showingSetup = pairing != .paired || !settings.setupDone
        talk.model = self
        DropNotes.shared.install()
    }

    // MARK: Pairing

    func refreshPairing() {
        pairing = record.status
    }

    /// Pair from a pasted link, an ira:// link, or a typed code and address.
    /// Returns nil when it worked, else what to tell the person.
    func pair(entry: String, server: String?) async -> String? {
        let target: (server: String, code: String)
        do {
            target = try Pairing.parse(entry, server: server)
        } catch {
            return (error as? Pairing.Failure)?.message ?? error.localizedDescription
        }
        busy = StepWords.pairing
        defer { busy = nil }
        do {
            let paired = try await Pairing.exchange(server: target.server, code: target.code)
            if pairing == .paired { await disconnectDevice() }
            try record.adopt(paired)
            settings.newConversation()
            talk.reset()
            refreshPairing()
            info = nil
            notice = nil
            await loadInfo()
            connectDevice()
            return nil
        } catch let failure as Pairing.Failure {
            return failure.message
        } catch {
            return "The Keychain did not keep this iPhone's key: \(error.localizedDescription). Try again."
        }
    }

    /// An `ira://pair?server=...&code=...` link from the pair page. Any app or web page can
    /// open one, so nothing changes until the person says yes on a sheet that names the
    /// new Ira, and the one this iPhone would leave.
    func open(_ url: URL) async {
        guard url.scheme == "ira" else { return }
        do {
            let target = try Pairing.parse(url.absoluteString, server: nil)
            let current = pairing == .paired && !settings.server.isEmpty ? settings.server : nil
            linkToConfirm = LinkPair(server: target.server, code: target.code, current: current)
        } catch {
            notice = (error as? Pairing.Failure)?.message ?? error.localizedDescription
        }
    }

    /// The person said yes to the pairing link.
    func pairWithLink() async {
        guard let link = linkToConfirm else { return }
        linkToConfirm = nil
        showingSetup = true
        if let problem = await pair(entry: link.code, server: link.server) {
            notice = problem
        }
    }

    // MARK: The server

    func dropClient() -> DropClient? {
        guard pairing == .paired, !settings.server.isEmpty else { return nil }
        let secrets = self.secrets
        return DropClient(server: settings.server, token: { secrets.load(SecretAccount.device) })
    }

    func client() -> AskClient? {
        guard pairing == .paired, !settings.server.isEmpty else { return nil }
        let secrets = self.secrets
        return AskClient(server: settings.server, token: { secrets.load(SecretAccount.device) })
    }

    /// Ask the server what it can do (live calls, its voice), and whether it still knows this iPhone.
    @discardableResult
    func loadInfo() async -> ServerInfo? {
        guard let client = client() else { return nil }
        do {
            let loaded = try await client.info()
            info = loaded
            settings.assistantName = loaded.name
            if !loaded.canAsk {
                notice = "Your Ira account may not talk to Ira. Ask the person who runs your Ira to give your account a role that may."
            }
            return loaded
        } catch let failure as AskClient.Failure {
            if failure.signedOut {
                notice = "Your Ira no longer knows this iPhone (it was removed on Your devices). Pair it again in Settings."
            } else {
                notice = failure.message
            }
            return nil
        } catch {
            notice = error.localizedDescription
            return nil
        }
    }

    // MARK: The device connection

    func connectDevice() {
        guard pairing == .paired, device == nil,
            let url = Pairing.websocketURL(server: settings.server)
        else { return }
        let secrets = self.secrets
        let toolbox = Toolbox(
            permissions: permissions, eventKit: eventKit,
            opener: { url in await AppModel.openURL(url) },
            foreground: { await MainActor.run { AppModel.shared.foreground } },
            record: { activity in Task { @MainActor in AppModel.shared.recordActivity(activity) } })
        let client = DeviceClient(
            url: url, token: { secrets.load(SecretAccount.device) }, tools: toolbox, label: settings.deviceLabel,
            onState: { state in Task { @MainActor in AppModel.shared.deviceChanged(state) } })
        client.onDrop = { change in Task { @MainActor in AppModel.shared.drop.handle(change) } }
        device = client
        client.start()
    }

    func disconnectDevice() async {
        device?.stop()
        device = nil
        deviceState = .stopped
    }

    private func deviceChanged(_ state: DeviceState) {
        var wasConnected = false
        if case .connected = deviceState { wasConnected = true }
        deviceState = state
        if case .connected(_, let skills) = state {
            skillsOn = skills
            if !wasConnected { Task { await drop.catchUp() } }  // what arrived while away
        }
        if state == .refused { refreshPairing() }
    }

    private func recordActivity(_ item: Activity) {
        activity.insert(item, at: 0)
        if activity.count > 50 { activity.removeLast(activity.count - 50) }
    }

    /// The app came on screen or left it. iOS suspends an app off screen, which
    /// ends its connections; a call keeps the app awake, so its connection stays.
    func phaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .active:
            foreground = true
            refreshPairing()
            permissionsChecked = Date()
            if pairing == .paired {
                connectDevice()
                device?.reconnectNow()
                if info == nil { Task { await loadInfo() } }
            }
            if callRequested, !showingSetup {
                callRequested = false
                talk.startCall()
            }
        case .background:
            foreground = false
            if !talk.inCall {
                device?.stop()
                device = nil
                deviceState = .stopped
            }
        default:
            foreground = phase == .active
        }
    }

    // MARK: Get Ira ready

    var rows: [ChecklistRow] {
        _ = permissionsChecked
        let paired = pairing == .paired
        return Checklist.rows(paired: paired) { [permissions] item in permissions.state(item) }
    }

    var ready: Bool { Checklist.ready(rows) }

    func allow(_ item: ChecklistItem) async {
        busy = "Waiting for your answer to iOS…"
        _ = await permissions.request(item)
        busy = nil
        permissionsChecked = Date()
    }

    /// Open a link with iOS (a tel: link shows the iPhone's own Call prompt).
    static func openURL(_ url: URL) async -> Bool {
        await UIApplication.shared.open(url)
    }

    func openSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
    }

    func finishSetup() {
        settings.setupDone = true
        showingSetup = false
        if callRequested {
            callRequested = false
            talk.startCall()
        }
    }

    /// The Siri shortcut "Talk to Ira": start a call once the app is on screen.
    func requestCall() {
        if foreground && !showingSetup && pairing == .paired {
            talk.startCall()
        } else {
            callRequested = true
        }
    }

    // MARK: Leaving

    /// Tell the server to forget this iPhone, then forget the key and the server here.
    func removeThisIPhone() async {
        busy = "Removing this iPhone from your Ira…"
        talk.endCall()
        let client = device
        device = nil
        client?.stop()
        if let url = Pairing.websocketURL(server: settings.server) {
            let secrets = self.secrets
            let goodbye = DeviceClient(
                url: url, token: { secrets.load(SecretAccount.device) }, tools: EmptyTools(), label: settings.deviceLabel)
            if !(await goodbye.sayGoodbye()) {
                notice = "Your Ira could not be told. This iPhone forgot it anyway; remove it on Your devices too."
            }
        }
        record.removeOnPurpose()
        talk.reset()
        info = nil
        activity.removeAll()
        refreshPairing()
        deviceState = .stopped
        busy = nil
        showingSetup = true
    }
}

/// No tools: for the goodbye, which never says hello.
struct EmptyTools: ToolRunner {
    var definitions: [JSONValue] { [] }
    func call(_ name: String, args: JSONValue) async throws -> JSONValue { throw ToolFailure("no tools") }
}

/// A pairing link to confirm: the Ira it pairs with, and the one this iPhone is paired with now.
struct LinkPair: Identifiable, Equatable {
    let server: String
    let code: String
    let current: String?
    var id: String { server + code }
}
