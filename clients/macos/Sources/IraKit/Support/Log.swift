import Foundation

/// Logs that are safe to keep: what happened and how long it took, never content.
///
/// Nothing in the app passes file text, screen text, transcripts or answers to
/// the log. As a second line of defence every line goes through `redact`:
/// device and session tokens are masked, pairing codes hidden, and addresses
/// lose their query and fragment. Lines go to `~/Library/Logs/Ira/ira.log`,
/// which rolls over to `ira.log.1` at 1 MB.
public final class IraLog: @unchecked Sendable {
    public static let shared = IraLog()

    public let fileURL: URL?
    private let queue = DispatchQueue(label: "in.ira.mac.log")
    private let maxBytes: Int
    private let formatter: ISO8601DateFormatter

    public init(directory: URL? = IraLog.defaultDirectory, maxBytes: Int = 1_000_000) {
        self.maxBytes = maxBytes
        self.formatter = ISO8601DateFormatter()
        if let directory {
            try? FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700])
            fileURL = directory.appendingPathComponent("ira.log")
        } else {
            fileURL = nil
        }
    }

    public static var defaultDirectory: URL? {
        FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first?
            .appendingPathComponent("Logs/Ira", isDirectory: true)
    }

    public func info(_ message: String) { write("INFO", message) }
    public func warning(_ message: String) { write("WARN", message) }

    private func write(_ level: String, _ message: String) {
        let line = "\(formatter.string(from: Date())) \(level) \(IraLog.redact(message))\n"
        guard let fileURL else { return }
        queue.async { [maxBytes] in
            let manager = FileManager.default
            if let size = (try? manager.attributesOfItem(atPath: fileURL.path))?[.size] as? Int,
                size > maxBytes
            {
                let old = fileURL.appendingPathExtension("1")
                try? manager.removeItem(at: old)
                try? manager.moveItem(at: fileURL, to: old)
            }
            if !manager.fileExists(atPath: fileURL.path) {
                manager.createFile(
                    atPath: fileURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
            }
            guard let handle = try? FileHandle(forWritingTo: fileURL) else { return }
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: Data(line.utf8))
        }
    }

    public static let maxLine = 500

    /// Mask secrets in a log line: tokens, pairing codes, URL queries; and cut it short.
    public static func redact(_ text: String) -> String {
        var out = text
        let rules: [(String, String)] = [
            (#"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s?#"'<>]*)[?#][^\s"'<>]*"#, "$1"),
            (#"\birad_[A-Za-z0-9_-]+"#, "irad_***"),
            (#"\bira_[st]_[A-Za-z0-9_-]+"#, "ira_*_***"),
            (#"(?i)(code=)[A-Za-z0-9-]+"#, "$1***"),
            (#"(?i)(bearer\s+)\S+"#, "$1***"),
        ]
        for (pattern, template) in rules {
            out = out.replacingOccurrences(
                of: pattern, with: template, options: .regularExpression)
        }
        if out.count > maxLine {
            out = String(out.prefix(maxLine)) + "..."
        }
        return out
    }
}
