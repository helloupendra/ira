import AppKit
import Foundation
import IraKit

/// The app's state: pairing, the device connection, the tools, and "What I read".
@MainActor
final class AppModel: ObservableObject {
    enum Screen { case pair, permissions, chat }

    @Published var screen: Screen = .pair
    @Published var deviceState: DeviceState = .stopped
    @Published var activity: [Activity] = []
    @Published var assistant: String

    let settings: AppSettings
    let secrets: SecretStore
    let conversation: Conversation
    private var device: DeviceClient?
    private var toolbox: Toolbox?
    /// The app that was in front before Ira's window, for "what is on my screen".
    private var lastOtherApp: (pid: pid_t, name: String)?
    private var observers: [NSObjectProtocol] = []

    init(settings: AppSettings = AppSettings(), secrets: SecretStore = KeychainStore()) {
        self.settings = settings
        self.secrets = secrets
        self.assistant = settings.assistantName
        self.conversation = Conversation(settings: settings, secrets: secrets)
        trackFrontApp()
        route()
        if paired { startDevice() }
    }

    var paired: Bool {
        !settings.server.isEmpty && secrets.load(SecretAccount.device) != nil
    }

    func route() {
        if !paired {
            screen = .pair
        } else if !settings.firstRunDone {
            screen = .permissions
        } else {
            screen = .chat
        }
    }

    // MARK: Pairing

    func pair(entry: String, server: String?) async throws {
        let known = server?.isEmpty == false ? server : (settings.server.isEmpty ? nil : settings.server)
        let (address, code) = try Pairing.parse(entry, server: known)
        let paired = try await Pairing.exchange(server: address, code: code)
        guard TokenShape.isDeviceToken(paired.token) else {
            throw Pairing.Failure("the server's answer did not hold a device token")
        }
        stopDevice()
        conversation.disconnect()
        try secrets.save(paired.token, account: SecretAccount.device)
        settings.server = paired.server
        settings.deviceID = paired.deviceID
        settings.deviceLabel = paired.label
        if let name = paired.assistant, !name.isEmpty {
            settings.assistantName = name
            assistant = name
        }
        IraLog.shared.info("paired as device \(paired.deviceID)")
        startDevice()
        route()
    }

    /// Remove this Mac: the server revokes its token, and the app forgets it.
    func forget() async {
        if let device { _ = await device.sayGoodbye() }
        stopDevice()
        conversation.clear()
        secrets.delete(SecretAccount.device)
        if let session = secrets.load(SecretAccount.session) {
            await AskClient(server: settings.server, token: { session }).signOut()
            secrets.delete(SecretAccount.session)
        }
        settings.forgetPairing()
        activity.removeAll()
        IraLog.shared.info("this Mac was removed")
        route()
    }

    /// Sign in for typing and recorded voice when live voice is not available.
    func signIn(email: String, password: String) async throws {
        let token = try await AskClient.signIn(server: settings.server, email: email, password: password)
        try secrets.save(token, account: SecretAccount.session)
        settings.signedInEmail = email
        conversation.needsSignIn = false
        conversation.notice = nil
        conversation.disconnect()
    }

    func signOut() async {
        if let session = secrets.load(SecretAccount.session) {
            await AskClient(server: settings.server, token: { session }).signOut()
        }
        secrets.delete(SecretAccount.session)
        settings.signedInEmail = nil
        conversation.disconnect()
    }

    // MARK: The device connection

    func startDevice() {
        guard device == nil, let url = Pairing.websocketURL(server: settings.server) else { return }
        let secrets = self.secrets
        let settings = self.settings
        let toolbox = Toolbox(
            policy: { PathPolicy.current(settings: settings) },
            frontApp: { [weak self] in await self?.frontApp() },
            record: { [weak self] activity in
                Task { @MainActor in self?.remember(activity) }
            })
        self.toolbox = toolbox
        let client = DeviceClient(
            url: url, token: { secrets.load(SecretAccount.device) }, tools: toolbox,
            label: settings.deviceLabel,
            onState: { [weak self] state in
                Task { @MainActor in self?.deviceState = state }
            })
        device = client
        // A coding task's "done" or "failed" reaches the person through the server.
        toolbox.tasks.announce = { [weak client] event, title, text, data in
            client?.announce(event: event, title: title, text: text, data: data)
        }
        client.start()
    }

    func stopDevice() {
        device?.stop()
        device = nil
        toolbox = nil
    }

    func reconnect() {
        device?.reconnectNow()
    }

    /// Say hello again, so the server learns a changed tool list (tasks set up or removed).
    func reloadTools() {
        stopDevice()
        startDevice()
    }

    var tasksConfigured: Bool { TaskSettings.load() != nil }

    private func remember(_ entry: Activity) {
        activity.insert(entry, at: 0)
        if activity.count > 50 { activity.removeLast(activity.count - 50) }
    }

    // MARK: The app in front

    private func trackFrontApp() {
        let center = NSWorkspace.shared.notificationCenter
        observers.append(center.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                app.processIdentifier != getpid()
            else { return }
            let entry = (app.processIdentifier, app.localizedName ?? "the app in front")
            MainActor.assumeIsolated { self?.lastOtherApp = entry }
        })
        observers.append(center.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.reconnect() }
        })
    }

    func frontApp() -> (pid: pid_t, name: String)? {
        if let front = NSWorkspace.shared.frontmostApplication, front.processIdentifier != getpid() {
            return (front.processIdentifier, front.localizedName ?? "the app in front")
        }
        return lastOtherApp
    }

    func finishFirstRun() {
        settings.firstRunDone = true
        route()
    }
}
