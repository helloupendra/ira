import AppKit
import AVFoundation
import Contacts
import CoreServices
import EventKit
import IraKit
import ServiceManagement
import Speech

/// Every permission macOS asks about for Ira, whether it is given, and where to
/// change it: for the first-run checklist and the Settings window.
struct Permission: Identifiable, Equatable {
    enum State: Equatable {
        case granted
        case missing
        /// Not asked yet: macOS asks the first time Ira needs it.
        case notAsked
        /// macOS does not say until Ira first uses it.
        case unknown
    }

    let id: String
    let title: String
    let why: String
    let icon: String
    var state: State
    /// The Privacy & Security page that holds it.
    let pane: String
    /// Whether Ira can ask for it from a button (some only ask when first used).
    let askable: Bool
}

@MainActor
final class PermissionCenter: ObservableObject {
    @Published private(set) var all: [Permission] = []

    /// Apps Ira drives with Apple Events, by bundle id.
    static let automated: [(name: String, bundleID: String)] = [
        ("Mail", "com.apple.mail"), ("Notes", "com.apple.Notes"), ("Messages", "com.apple.MobileSMS"),
        ("Google Chrome", "com.google.Chrome"), ("Safari", "com.apple.Safari"),
    ]

    init() { refresh() }

    func refresh() {
        func eventKit(_ type: EKEntityType) -> Permission.State {
            switch EKEventStore.authorizationStatus(for: type) {
            case .fullAccess, .authorized: return .granted
            case .notDetermined: return .notAsked
            default: return .missing
            }
        }
        let mic: Permission.State = {
            switch AVCaptureDevice.authorizationStatus(for: .audio) {
            case .authorized: return .granted
            case .notDetermined: return .notAsked
            default: return .missing
            }
        }()
        let contacts: Permission.State = {
            switch CNContactStore.authorizationStatus(for: .contacts) {
            case .authorized: return .granted
            case .notDetermined: return .notAsked
            default: return .missing
            }
        }()
        let speech: Permission.State = {
            switch SFSpeechRecognizer.authorizationStatus() {
            case .authorized: return .granted
            case .notDetermined: return .notAsked
            default: return .missing
            }
        }()
        var list = [
            Permission(id: "mic", title: "Microphone",
                       why: "So you can talk to Ira. It listens only after you press the mic, or say “Hey Ira” if you switched that on.",
                       icon: "mic", state: mic, pane: "Privacy_Microphone", askable: true),
            Permission(id: "screen", title: "Screen Recording",
                       why: "Only for “what is on my screen?”. Ira reads the words of the window in front on this Mac and sends only the words.",
                       icon: "macwindow", state: ScreenText.permitted ? .granted : .missing, pane: "Privacy_ScreenCapture", askable: true),
            Permission(id: "files", title: "Files and Folders",
                       why: "So Ira can read a file you ask about. macOS asks the first time Ira opens something in Documents, Desktop or Downloads.",
                       icon: "folder", state: .unknown, pane: "Privacy_FilesAndFolders", askable: false),
            Permission(id: "contacts", title: "Contacts",
                       why: "So Ira can put a name to a number, or find the number or email to write to.",
                       icon: "person.crop.circle", state: contacts, pane: "Privacy_Contacts", askable: true),
            Permission(id: "calendar", title: "Calendars",
                       why: "So Ira can tell you what is on your day, and add an event after your yes.",
                       icon: "calendar", state: eventKit(.event), pane: "Privacy_Calendars", askable: true),
            Permission(id: "reminders", title: "Reminders",
                       why: "So Ira can read your reminders and add one when you ask.",
                       icon: "checklist", state: eventKit(.reminder), pane: "Privacy_Reminders", askable: true),
            Permission(id: "speech", title: "Speech Recognition",
                       why: "Only for “Hey Ira”: the Mac listens for those words on its own, and nothing leaves it until it hears them.",
                       icon: "waveform", state: speech, pane: "Privacy_SpeechRecognition", askable: true),
        ]
        for app in PermissionCenter.automated {
            list.append(Permission(
                id: "automation-\(app.bundleID)", title: "Automation: \(app.name)",
                why: PermissionCenter.automationReason(app.name),
                icon: "gearshape.2", state: PermissionCenter.automation(app.bundleID), pane: "Privacy_Automation", askable: true))
        }
        all = list
    }

    static func automationReason(_ app: String) -> String {
        switch app {
        case "Mail": return "So Ira can search your inbox, read an email, and draft one for you to send."
        case "Notes": return "So Ira can search, read and add notes."
        case "Messages": return "So Ira can send an iMessage after your yes."
        default: return "So Ira can list your \(app) tabs and bring one to the front. Never page contents or passwords."
        }
    }

    /// Whether Ira may send Apple Events to an app, without asking (and without starting it).
    static func automation(_ bundleID: String) -> Permission.State {
        let target = NSAppleEventDescriptor(bundleIdentifier: bundleID)
        guard let desc = target.aeDesc else { return .unknown }
        let status = AEDeterminePermissionToAutomateTarget(desc, typeWildCard, typeWildCard, false)
        switch status {
        case noErr: return .granted
        case OSStatus(errAEEventWouldRequireUserConsent): return .notAsked
        case OSStatus(errAEEventNotPermitted): return .missing
        default: return .unknown  // the app is not running, or not installed
        }
    }

    /// Ask for one permission (macOS shows its own dialog), then look again.
    func ask(_ permission: Permission) async {
        switch permission.id {
        case "mic": _ = await AVCaptureDevice.requestAccess(for: .audio)
        case "screen": ScreenText.requestPermission()
        case "contacts": _ = try? await CNContactStore().requestAccess(for: .contacts)
        case "calendar": _ = try? await EKEventStore().requestFullAccessToEvents()
        case "reminders": _ = try? await EKEventStore().requestFullAccessToReminders()
        case "speech":
            await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { _ in continuation.resume() }
            }
        default:
            if permission.id.hasPrefix("automation-") {
                let bundleID = String(permission.id.dropFirst("automation-".count))
                let target = NSAppleEventDescriptor(bundleIdentifier: bundleID)
                if let desc = target.aeDesc {
                    // Asking needs the app running; macOS then shows "Ira wants to control ...".
                    _ = await Task.detached { AEDeterminePermissionToAutomateTarget(desc, typeWildCard, typeWildCard, true) }.value
                }
            }
        }
        refresh()
        if let now = all.first(where: { $0.id == permission.id }), now.state != .granted {
            open(now)
        }
    }

    func open(_ permission: Permission) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(permission.pane)") {
            NSWorkspace.shared.open(url)
        }
    }
}

/// Starting Ira when the person logs in, as the companion's LaunchAgent did.
enum LoginItem {
    static var enabled: Bool { SMAppService.mainApp.status == .enabled }

    /// Switch it on or off; a plain sentence when macOS says no.
    static func set(_ on: Bool) -> String? {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            return nil
        } catch {
            if SMAppService.mainApp.status == .requiresApproval {
                SMAppService.openSystemSettingsLoginItems()
                return "macOS wants you to allow Ira under Login Items in System Settings."
            }
            return on
                ? "Ira could not add itself to your login items. Add it in System Settings → General → Login Items."
                : "Ira could not remove itself from your login items. Remove it in System Settings → General → Login Items."
        }
    }
}
