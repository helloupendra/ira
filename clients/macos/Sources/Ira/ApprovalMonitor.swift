import AppKit
import Foundation
import IraKit

/// Whether an approval window is open for this Mac, and for how long: shown as
/// a banner with Stop in the window, and as an orange mark in the menu bar.
///
/// The server opens a window when the person confirms a control step with their
/// PIN (here, on the web or in Telegram); the app learns of it by asking, after
/// a confirm here, when the device connects, and when a covered tool runs.
@MainActor
final class ApprovalMonitor: ObservableObject {
    @Published private(set) var window: ApprovalWindow?
    @Published private(set) var now = Date()
    @Published private(set) var problem: String?
    /// Apps on this Mac where Ira may act without asking (bundle ids), from the server.
    @Published private(set) var trustedApps: [String] = []

    private let settings: AppSettings
    private let secrets: SecretStore
    private var ticker: Timer?
    private var lastAsked = Date.distantPast
    private var asking = false

    init(settings: AppSettings, secrets: SecretStore) {
        self.settings = settings
        self.secrets = secrets
    }

    var remaining: TimeInterval? {
        guard let window else { return nil }
        let left = window.expiresAt.timeIntervalSince(now)
        return left > 0 ? left : nil
    }

    /// "Ira can control this Mac for 12 more minutes", while a window is open.
    var banner: String? { remaining.map(Approvals.banner(remaining:)) }

    private func client() -> AskClient? {
        guard !settings.server.isEmpty, let token = secrets.load(SecretAccount.device) else { return nil }
        return AskClient(server: settings.server, token: { token })
    }

    /// Ask the server now.
    func refresh() async {
        guard !asking, let client = client(), let deviceID = settings.deviceID else { return }
        asking = true
        defer { asking = false }
        lastAsked = Date()
        do {
            let state = Approvals.parse(try await client.approvals())
            trustedApps = state.trustedApps[deviceID] ?? []
            show(state.windows.first { $0.deviceID == deviceID })
        } catch let failure as AskClient.Failure where failure.status == 404 {
            show(nil)  // a server without approvals
        } catch {
            // Offline: keep what is known; the clock still runs it out.
        }
    }

    /// Ask unless asked within `seconds`: after a covered tool ran, or the window opened.
    func refreshIfStale(_ seconds: TimeInterval = 10) {
        guard Date().timeIntervalSince(lastAsked) > seconds else { return }
        Task { await refresh() }
    }

    /// A trusted app's name on this Mac, or its bundle id when it is not installed.
    static func name(of bundleID: String) -> String {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else { return bundleID }
        return FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")
    }

    func openTrustedAppsPage() {
        if let link = Approvals.manageLink(server: settings.server) { NSWorkspace.shared.open(link) }
    }

    /// Stop the window at once: the next control step asks for the PIN again.
    func stop() async {
        guard let client = client() else { return }
        let id = window?.id
        do {
            try await client.stopApproval(id)
            problem = nil
            IraLog.shared.info("approval window stopped from this Mac")
        } catch let failure as AskClient.Failure where failure.status == 404 {
            problem = nil  // it had ended already
        } catch {
            problem = "Ira could not be reached to stop it: \(error.localizedDescription)"
        }
        await refresh()
    }

    private func show(_ window: ApprovalWindow?) {
        let opened = self.window == nil && window != nil
        self.window = window
        now = Date()
        if opened { IraLog.shared.info("approval window open on this Mac") }
        if window != nil {
            if ticker == nil {
                ticker = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                    MainActor.assumeIsolated { self?.tick() }
                }
            }
        } else {
            ticker?.invalidate()
            ticker = nil
        }
    }

    private func tick() {
        now = Date()
        if remaining == nil {
            show(nil)
        } else if now.timeIntervalSince(lastAsked) > 30 {
            // Stopped elsewhere, renewed by another PIN, or steps counted: look again.
            Task { await refresh() }
        }
    }
}
