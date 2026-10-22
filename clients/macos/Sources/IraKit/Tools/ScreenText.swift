import AppKit
import CoreGraphics
import Foundation
import ScreenCaptureKit
import Vision

/// Reading the window in front: ScreenCaptureKit takes the picture, Vision reads
/// the text on this Mac, and only the text leaves it. The picture is dropped as
/// soon as it is read.
public enum ScreenText {
    public struct Window: Equatable, Sendable {
        public let id: CGWindowID
        public let app: String
        public let title: String
        public let pid: pid_t
    }

    public static var permitted: Bool { CGPreflightScreenCaptureAccess() }

    /// Whether Screen Recording was allowed when Ira started. macOS applies a
    /// grant only to a fresh start: allowed later, the capture hangs until Ira
    /// is reopened. The app reads it once at launch (`noteLaunch`).
    nonisolated(unsafe) public private(set) static var permittedAtLaunch = true

    public static func noteLaunch() {
        permittedAtLaunch = CGPreflightScreenCaptureAccess()
    }

    /// Apps whose windows Ira never reads: System Settings (whose privacy pages
    /// macOS protects, and whose capture can hang), the login and password
    /// prompts, and password managers.
    public static let neverRead: [String: String] = [
        "com.apple.systempreferences": "System Settings",
        "com.apple.SecurityAgent": "the password prompt",
        "com.apple.loginwindow": "the login window",
        "com.apple.keychainaccess": "Keychain Access",  // pragma: allowlist secret
        "com.apple.Passwords": "Passwords",  // pragma: allowlist secret
        "com.1password.1password": "1Password",  // pragma: allowlist secret
        "com.agilebits.onepassword7": "1Password",  // pragma: allowlist secret
        "com.bitwarden.desktop": "Bitwarden",
        "com.lastpass.LastPass": "LastPass",
        "com.dashlane.Dashlane": "Dashlane",
    ]

    /// macOS's own prompts and system parts: in front, they are a question for
    /// the person, not the window they mean.
    public static let systemUI: Set<String> = [
        "com.apple.UserNotificationCenter", "com.apple.coreservices.uiagent", "com.apple.CoreServicesUIAgent",
        "com.apple.tccd", "com.apple.controlcenter", "com.apple.notificationcenterui", "com.apple.dock",
        "com.apple.systemuiserver", "com.apple.WindowManager",
    ]

    /// Why the front app's window is not read, or nil.
    public static func refusal(bundleID: String?, name: String) -> String? {
        if let bundleID, systemUI.contains(bundleID) {
            return "a macOS prompt is in front (\(name)). Answer it, then ask again"
        }
        guard let bundleID, let known = neverRead[bundleID] else { return nil }
        if bundleID == "com.apple.systempreferences" {
            return "I can't read System Settings' window: macOS keeps it private. Bring the window you mean to the front and ask again"
        }
        return "I never read \(known)'s window: it can show passwords. Bring the window you mean to the front and ask again"
    }

    /// Ask macOS to add Ira to the Screen Recording list (it shows its own dialog once).
    @discardableResult
    public static func requestPermission() -> Bool { CGRequestScreenCaptureAccess() }

    public static let restartNeeded =
        "macOS needs Ira restarted after the Screen Recording permission. Quit Ira and open it again"

    /// Ira is about to capture the screen, and macOS may ask the person first
    /// (monthly on macOS 15 and later): the app keeps its window out of the way.
    public static let capturing = Notification.Name("in.ira.mac.capturing")
    public static let captured = Notification.Name("in.ira.mac.captured")

    public static let notPermitted =
        "Screen Recording is off for Ira, so I cannot read the screen. Allow Ira in System Settings → Privacy & Security → Screen & System Audio Recording, then ask again"

    /// The front window of `pid`: the first normal window in macOS's front-to-back order.
    public static func frontWindow(of pid: pid_t) -> Window? {
        guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]]
        else { return nil }
        for info in list {
            guard (info[kCGWindowOwnerPID as String] as? Int).map(pid_t.init) == pid,
                (info[kCGWindowLayer as String] as? Int) == 0,
                let id = info[kCGWindowNumber as String] as? Int
            else { continue }
            if let bounds = info[kCGWindowBounds as String] as? [String: Any],
                let width = bounds["Width"] as? Double, let height = bounds["Height"] as? Double,
                width < 80 || height < 60
            {
                continue
            }
            return Window(
                id: CGWindowID(id),
                app: info[kCGWindowOwnerName as String] as? String ?? "",
                title: info[kCGWindowName as String] as? String ?? "",
                pid: pid)
        }
        return nil
    }

    /// A picture of one window, at the screen's own resolution.
    public static func capture(_ window: Window) async throws -> CGImage {
        NotificationCenter.default.post(name: capturing, object: nil)
        defer { NotificationCenter.default.post(name: captured, object: nil) }
        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        } catch {
            // Allowed in System Settings, yet refused here: the permission came while
            // Ira was running, and macOS applies it only to a fresh start.
            if permitted { throw ToolFailure(restartNeeded) }
            throw ToolFailure(notPermitted)
        }
        guard let target = content.windows.first(where: { $0.windowID == window.id }) else {
            throw ToolFailure("that window is no longer on screen")
        }
        let filter = SCContentFilter(desktopIndependentWindow: target)
        let configuration = SCStreamConfiguration()
        let scale = Double(filter.pointPixelScale)
        configuration.width = max(1, Int(target.frame.width * scale))
        configuration.height = max(1, Int(target.frame.height * scale))
        configuration.showsCursor = false
        configuration.ignoreShadowsSingleWindow = true
        return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
    }

    /// Languages to read, English and Hindi first, as far as this Mac's Vision knows them.
    public static func languages() -> [String] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        let supported = (try? request.supportedRecognitionLanguages()) ?? ["en-US"]
        let wanted = ["en-US", "hi-IN"].filter(supported.contains)
        return wanted.isEmpty ? ["en-US"] : wanted
    }

    /// The text in a picture, read on this Mac, in reading order.
    public static func recognize(_ image: CGImage, languages: [String] = ScreenText.languages()) throws -> String {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.recognitionLanguages = languages
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try handler.perform([request])
        let lines = (request.results ?? []).compactMap { observation -> TextLine? in
            guard let text = observation.topCandidates(1).first?.string else { return nil }
            return TextLine(text: text, box: observation.boundingBox)
        }
        return arrange(lines)
    }

    /// A piece of text Vision found, with its box (0-1, origin bottom left).
    public struct TextLine: Equatable, Sendable {
        public let text: String
        public let box: CGRect
        public init(text: String, box: CGRect) {
            self.text = text
            self.box = box
        }
    }

    /// Reading order: rows from the top, and left to right within a row. Pieces
    /// whose middles are within half a line's height share a row.
    public static func arrange(_ lines: [TextLine]) -> String {
        let sorted = lines.sorted { $0.box.midY > $1.box.midY }
        var rows: [[TextLine]] = []
        for line in sorted {
            if let last = rows.last?.first,
                abs(last.box.midY - line.box.midY) < max(last.box.height, line.box.height) / 2
            {
                rows[rows.count - 1].append(line)
            } else {
                rows.append([line])
            }
        }
        return rows.map { row in
            row.sorted { $0.box.minX < $1.box.minX }.map(\.text).joined(separator: "  ")
        }.joined(separator: "\n")
    }
}
