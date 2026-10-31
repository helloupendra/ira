import Foundation
import IraKit

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
