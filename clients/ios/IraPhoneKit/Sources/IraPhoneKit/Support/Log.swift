import Foundation
import os

/// Logs that are safe to keep: what happened and how long it took, never content.
///
/// Nothing in the app passes a transcript, an answer, a contact or a place to the
/// log; tool calls are logged by name and outcome. As a second line of defence,
/// tokens and pairing codes are masked. Lines go to the system log (Console.app,
/// subsystem `io.github.helloupendra.ira`), which iOS keeps on the phone.
public struct IraLog: Sendable {
    public static let shared = IraLog()
    private let logger = Logger(subsystem: IraPhone.bundleID, category: "ira")

    public init() {}

    public func info(_ message: String) {
        let line = IraLog.redact(message)
        logger.info("\(line, privacy: .public)")
    }

    public func warning(_ message: String) {
        let line = IraLog.redact(message)
        logger.warning("\(line, privacy: .public)")
    }

    /// Masks device and session tokens and pairing codes.
    public static func redact(_ message: String) -> String {
        var text = message
        for pattern in [#"irad_[A-Za-z0-9_-]+"#, #"ira_[st]_[A-Za-z0-9_-]+"#, #"code=[A-Za-z0-9-]+"#] {
            text = text.replacingOccurrences(of: pattern, with: "***", options: .regularExpression)
        }
        return text
    }
}
