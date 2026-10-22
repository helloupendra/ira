import AppKit
import Foundation
import IraKit

/// The app's state: pairing, the device connection, the tools, "What I read",
/// "Hey Ira", and taking over from the old companion.
@MainActor
final class AppModel: ObservableObject {
    enum Screen { case setup, chat, keyProblem }

    @Published var screen: Screen = .setup
    @Published var deviceState: DeviceState = .stopped
    @Published var activity: [Activity] = []
    @Published var assistant: String
    /// The old Python companion (retired) is still on this Mac.
    @Published var companion: Companion.Found?
    @Published var companionPresent = false
    /// Pairing again from Settings: the pairing page shows, and nothing is
    /// forgotten until a new pairing succeeds.
    @Published var repairing = false
    @Published var wakeListening = false
    @Published var wakeProblem: String?
    /// Keep the window on top while working in other apps.
    @Published var pinned: Bool {
        didSet { settings.panelPinned = pinned }
    }

    let settings: AppSettings
    let secrets: SecretStore
    let conversation: Conversation
    let permissions = PermissionCenter()
    let wake = WakeListener()
    /// Called when "Hey Ira" is heard: the window opens and listens.
    var onWake: (() -> Void)?
    private var device: DeviceClient?
    private var toolbox: Toolbox?
    private var routineTimer: Timer?
    private var routine: Routine?
    private var routineOn = false
    /// The app that was in front before Ira's window, for "what is on my screen".
    private var lastOtherApp: (pid: pid_t, name: String)?
    private var observers: [NSObjectProtocol] = []
    private let oldCompanion = Companion()

    init(settings: AppSettings = AppSettings(), secrets: SecretStore = KeychainStore()) {
        self.settings = settings
        self.secrets = secrets
        self.assistant = settings.assistantName
        self.pinned = settings.panelPinned
        self.conversation = Conversation(settings: settings, secrets: secrets)
        trackFrontApp()
        lookForCompanion()
        route()
        if paired { startDevice() }
        wake.onWake = { [weak self] in self?.heardWakePhrase() }
        conversation.onListeningEnded = { [weak self] in self?.resumeWake() }
        if settings.wakeWord { Task { await self.setWakeWord(true) } }
    }

    var record: PairingRecord { PairingRecord(settings: settings, secrets: secrets) }

    /// The pairing as last looked at: the Keychain is asked in `route`, not on
    /// every redraw, so it never shows its prompt more than once at a time.
    @Published private(set) var pairingStatus: PairingRecord.Status = .unpaired

    var paired: Bool { pairingStatus == .paired }

    func route() {
        pairingStatus = record.status
        switch pairingStatus {
        case .keyUnreadable:
            screen = repairing ? .setup : .keyProblem
        case .paired:
            screen = settings.firstRunDone && !repairing ? .chat : .setup
        case .unpaired:
            screen = .setup
        }
    }

    /// Look at the Keychain again (after "Always Allow"), and connect if it answers.
    func retryKey() {
        route()
        if paired { startDevice() }
    }

    /// Pair again from Settings: show the pairing page; the current pairing
    /// stays until the new one succeeds.
    func startRepair() {
        repairing = true
        route()
    }

    // MARK: Pairing

    func pair(entry: String, server: String?) async throws {
        let known = server?.isEmpty == false ? server : (settings.server.isEmpty ? nil : settings.server)
        let (address, code) = try Pairing.parse(entry, server: known)
        let paired = try await Pairing.exchange(server: address, code: code)
        guard TokenShape.isDeviceToken(paired.token) else {
            throw Pairing.Failure("the server's answer did not hold a device token")
        }
        try adopt(server: paired.server, token: paired.token, deviceID: paired.deviceID, label: paired.label)
        if let name = paired.assistant, !name.isEmpty {
            settings.assistantName = name
            assistant = name
        }
        IraLog.shared.info("paired as device \(paired.deviceID)")
        route()
    }

    private func adopt(server: String, token: String, deviceID: Int?, label: String) throws {
        stopDevice()
        conversation.disconnect()
        try record.adopt(server: server, token: token, deviceID: deviceID, label: label)
        repairing = false
        startDevice()
        route()
    }

    // MARK: The old companion

    func lookForCompanion() {
        companionPresent = oldCompanion.present
        companion = companionPresent ? oldCompanion.settings() : nil
    }

    /// Take over the companion's pairing (its server, key and network salt, so
    /// named networks keep their names), then remove it. Nothing changes on the
    /// server: the same device goes on, now with the app's tools.
    func takeOverCompanion() async throws {
        // Never over an existing pairing: that one stays until the person removes it.
        guard pairingStatus == .unpaired else {
            throw Pairing.Failure("this Mac is already paired; remove the old companion instead")
        }
        guard let found = oldCompanion.settings(), !found.server.isEmpty else {
            throw Pairing.Failure("the old companion was never paired; pair Ira for Mac with a new code")
        }
        guard let token = await oldCompanion.token() else {
            throw Pairing.Failure("the old companion's key is not in your Keychain any more; pair Ira for Mac with a new code")
        }
        if !found.networkSalt.isEmpty { settings.networkSalt = found.networkSalt }
        try adopt(server: found.server, token: token, deviceID: found.deviceID, label: found.label)
        if let tasks = found.tasks, !FileManager.default.fileExists(atPath: TaskSettings.defaultPath.path) {
            // The person's own task settings move with them, unchanged.
            try? FileManager.default.createDirectory(at: TaskSettings.defaultPath.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? Data(tasks.encoded().utf8).write(to: TaskSettings.defaultPath)
        }
        await oldCompanion.remove()
        lookForCompanion()
        IraLog.shared.info("took over from the companion")
    }

    /// Remove the companion without taking over: it says goodbye to the server first.
    func removeCompanion() async {
        if let found = oldCompanion.settings(), let url = Pairing.websocketURL(server: found.server),
            let token = await oldCompanion.token()
        {
            let goodbye = DeviceClient(url: url, token: { token }, tools: Toolbox.empty, label: found.label)
            _ = await goodbye.sayGoodbye()
        }
        await oldCompanion.remove()
        lookForCompanion()
    }

    // MARK: Leaving

    /// Remove this Mac from Ira, as the companion's uninstall.sh did: the server
    /// forgets the device (its key stops at once), and the app forgets
    /// everything it kept here. The app itself goes to the Bin by hand.
    func removeEverything() async {
        if let device { _ = await device.sayGoodbye() }
        stopDevice()
        await setWakeWord(false)
        conversation.clear()
        _ = LoginItem.set(false)
        if oldCompanion.present { await removeCompanion() }
        record.removeOnPurpose()  // the only place the key and the server are forgotten
        if let domain = Bundle.main.bundleIdentifier {
            settings.defaults.removePersistentDomain(forName: domain)
        }
        if let logs = IraLog.defaultDirectory { try? FileManager.default.removeItem(at: logs) }
        activity.removeAll()
        IraLog.shared.info("this Mac was removed")
        route()
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
        toolbox.onRestartNeeded = { [weak self] in
            Task { @MainActor in self?.conversation.needsRestart = true }
        }
        self.toolbox = toolbox
        let client = DeviceClient(
            url: url, token: { secrets.load(SecretAccount.device) }, tools: toolbox,
            label: settings.deviceLabel,
            onState: { [weak self] state in
                Task { @MainActor in self?.deviceState = state }
            })
        client.onWelcome = { [weak self] assistant, phrase in
            Task { @MainActor in
                guard let self else { return }
                if let assistant, !assistant.isEmpty {
                    self.settings.assistantName = assistant
                    self.assistant = assistant
                }
                if let phrase, !phrase.isEmpty { self.wake.phrase = phrase }
            }
        }
        device = client
        startRoutine(client)
        // A coding task's progress, "done" or "failed" reaches the person through the server.
        toolbox.tasks.announce = { [weak client] event, title, text, data in
            client?.announce(event: event, title: title, text: text, data: data)
        }
        client.start()
    }

    func stopDevice() {
        routineTimer?.invalidate()
        routineTimer = nil
        routine = nil
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

    /// The routine skill: read every 30 seconds, only while the skill is on.
    private func startRoutine(_ client: DeviceClient) {
        let routine = Routine(salt: settings.networkSalt) { [weak client] frame in client?.observe(frame) }
        self.routine = routine
        routineOn = false
        routineTimer = Timer.scheduledTimer(withTimeInterval: Routine.interval, repeats: true) { [weak self, weak client] _ in
            MainActor.assumeIsolated {
                guard let self, let client else { return }
                let on = client.skills.contains("routine")
                if on {
                    DispatchQueue.global(qos: .utility).async { routine.tick() }
                } else if self.routineOn {
                    routine.reset()
                }
                self.routineOn = on
            }
        }
    }

    private func remember(_ entry: Activity) {
        activity.insert(entry, at: 0)
        if activity.count > 50 { activity.removeLast(activity.count - 50) }
    }

    // MARK: "Hey Ira"

    /// Switch "Hey Ira" on or off. On: the Mac listens for the phrase by itself.
    func setWakeWord(_ on: Bool) async {
        settings.wakeWord = on
        wakeProblem = nil
        if on {
            do {
                try await wake.start()
            } catch {
                wakeProblem = error.localizedDescription
                settings.wakeWord = false
            }
        } else {
            wake.stop()
        }
        wakeListening = wake.listening
        permissions.refresh()
    }

    private func heardWakePhrase() {
        wakeListening = false
        onWake?()
        conversation.startListening()
    }

    /// Listen for the phrase again once a conversation stops listening.
    private func resumeWake() {
        guard settings.wakeWord, !wake.listening else { return }
        Task {
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !conversation.listening else { return }
            try? await wake.start()
            wakeListening = wake.listening
        }
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

extension Toolbox {
    /// A toolbox with no tools, for saying goodbye on someone else's behalf.
    static var empty: ToolRunner { NoTools() }
}

private struct NoTools: ToolRunner {
    var definitions: [JSONValue] { [] }
    func call(_ name: String, args: JSONValue) async throws -> JSONValue { throw ToolFailure("no tools") }
}
