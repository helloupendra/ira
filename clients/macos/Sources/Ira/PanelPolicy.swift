import Foundation
import IraKit

/// What Ira's window does when another app becomes active.
///
/// It never keeps the keyboard from anything else. It hides for an ordinary
/// app the person clicked (unless pinned), but only steps below a system
/// prompt (a permission dialog, a password sheet, a notification), and below
/// anything at all while Ira itself is asking macOS for a permission or
/// capturing the screen: the person is answering for Ira, and its window must
/// be there when they come back.
enum PanelPolicy {
    enum Action: Equatable {
        /// Out of the way: the person went to work in another app.
        case hide
        /// Below the prompt, without the keyboard, still on screen.
        case stepBelow
        /// On top, without the keyboard (pinned).
        case letGoOfKeyboard
    }

    /// The processes that show macOS's own prompts.
    static let systemPrompts: Set<String> = [
        "com.apple.UserNotificationCenter", "com.apple.SecurityAgent", "com.apple.tccd",
        "com.apple.coreservices.uiagent", "com.apple.CoreServicesUIAgent", "com.apple.accessibility.universalAccessAuthWarn",
        "com.apple.ScreenContinuity", "com.apple.replayd", "com.apple.controlcenter", "com.apple.notificationcenterui",
        "com.apple.systemuiserver", "com.apple.dock", "com.apple.Spotlight", "com.apple.loginwindow",
        "com.apple.screencaptureui", "com.apple.WindowManager",
    ]

    static func onOtherApp(bundleID: String?, pinned: Bool, askingPermission: Bool, capturing: Bool) -> Action {
        if askingPermission || capturing { return .stepBelow }
        if let bundleID, systemPrompts.contains(bundleID) { return .stepBelow }
        return pinned ? .letGoOfKeyboard : .hide
    }
}

extension Notification.Name {
    /// Ira asked macOS for a permission (object: nil); its answer came back.
    static let iraAskingPermission = PermissionPrompt.asking
    static let iraAskedPermission = PermissionPrompt.asked
}

/// Why Ira quit, kept for the log of the next start.
enum QuitReason {
    static let key = "lastQuitReason"

    static func set(_ reason: String) {
        UserDefaults.standard.set(reason, forKey: key)
    }

    /// The last run's reason, once (cleared after reading). Nil: it never said,
    /// so it crashed, was force-quit, or the Mac shut down.
    static func takeLast() -> String? {
        let reason = UserDefaults.standard.string(forKey: key)
        UserDefaults.standard.removeObject(forKey: key)
        return reason
    }
}
