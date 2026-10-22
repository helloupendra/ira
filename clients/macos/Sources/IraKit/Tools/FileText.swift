import AppKit
import Foundation
import PDFKit
import UniformTypeIdentifiers

/// The text of a file Ira was asked to read: PDF, Word, RTF, plain text or Markdown.
public enum FileText {
    public struct Read: Equatable, Sendable {
        public let text: String
        public let kind: String
        public let truncated: Bool
        public let pages: Int?
    }

    /// The most a file may weigh before Ira refuses to open it.
    public static let maxFileBytes = 64 * 1024 * 1024

    static let plainExtensions: Set<String> = [
        "txt", "text", "md", "markdown", "mdown", "csv", "tsv", "json", "log", "yaml", "yml",
        "xml", "html", "htm", "srt", "vtt", "tex", "ini", "toml",
    ]

    public static func read(_ url: URL, maxChars: Int) throws -> Read {
        let values = try? url.resourceValues(forKeys: [.isDirectoryKey, .fileSizeKey, .isRegularFileKey])
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw ToolFailure("there is no file at that path")
        }
        if values?.isDirectory == true {
            throw ToolFailure("that is a folder; ask me to find files in it instead")
        }
        if let size = values?.fileSize, size > maxFileBytes {
            throw ToolFailure("that file is larger than 64 MB; I read smaller files only")
        }
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "pdf":
            return try pdf(url, maxChars: maxChars)
        case "docx":
            let data = try load(url)
            return cut(try DocxText.extract(from: data), kind: "Word document", maxChars: maxChars)
        case "rtf", "rtfd", "doc", "odt", "wordml":
            return try attributed(url, ext: ext, maxChars: maxChars)
        default:
            if plainExtensions.contains(ext) || conformsToText(url) {
                return cut(try plain(url, ext: ext), kind: kindName(ext), maxChars: maxChars)
            }
            throw ToolFailure(
                "I can read PDF, Word (.docx), RTF, text and Markdown files, not .\(ext.isEmpty ? "this kind" : ext) files")
        }
    }

    static func kindName(_ ext: String) -> String {
        switch ext {
        case "md", "markdown", "mdown": return "Markdown"
        case "csv", "tsv": return "table (CSV)"
        case "html", "htm": return "web page"
        default: return "text"
        }
    }

    private static func conformsToText(_ url: URL) -> Bool {
        guard let type = UTType(filenameExtension: url.pathExtension) else { return false }
        return type.conforms(to: .text) && !type.conforms(to: .rtf)
    }

    private static func load(_ url: URL) throws -> Data {
        do {
            return try Data(contentsOf: url, options: .mappedIfSafe)
        } catch {
            throw permission(error)
        }
    }

    /// A read macOS refused is almost always a folder permission: say so plainly.
    static func permission(_ error: Error) -> ToolFailure {
        let error = error as NSError
        if error.domain == NSCocoaErrorDomain && error.code == NSFileReadNoPermissionError
            || error.domain == NSPOSIXErrorDomain && error.code == Int(EPERM)
        {
            return ToolFailure(
                "macOS did not let Ira open that file. Allow Ira in System Settings → Privacy & Security → Files and Folders, then ask again")
        }
        return ToolFailure("that file could not be opened")
    }

    static func plain(_ url: URL, ext: String) throws -> String {
        let data = try load(url)
        var text = String(data: data, encoding: .utf8)
            ?? String(data: data, encoding: .utf16)
            ?? String(data: data, encoding: .windowsCP1252)
            ?? String(decoding: data, as: UTF8.self)
        if ext == "html" || ext == "htm" {
            text = stripTags(text)
        }
        return text
    }

    /// A web page's text without scripts, styles and tags.
    static func stripTags(_ html: String) -> String {
        var text = html
        for pattern in [#"(?is)<script\b.*?</script>"#, #"(?is)<style\b.*?</style>"#] {
            text = text.replacingOccurrences(of: pattern, with: " ", options: .regularExpression)
        }
        text = text.replacingOccurrences(of: #"(?i)<(br|/p|/div|/li|/h[1-6])\b[^>]*>"#, with: "\n", options: .regularExpression)
        text = text.replacingOccurrences(of: #"<[^>]{0,2000}>"#, with: " ", options: .regularExpression)
        for (entity, char) in [("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'"), ("&amp;", "&")] {
            text = text.replacingOccurrences(of: entity, with: char)
        }
        return text
    }

    static func attributed(_ url: URL, ext: String, maxChars: Int) throws -> Read {
        let type: NSAttributedString.DocumentType
        let kind: String
        switch ext {
        case "rtf": type = .rtf; kind = "RTF document"
        case "rtfd": type = .rtfd; kind = "RTF document"
        case "doc": type = .docFormat; kind = "Word document"
        case "odt": type = .openDocument; kind = "OpenDocument text"
        default: type = .wordML; kind = "Word document"
        }
        do {
            let string = try NSAttributedString(
                url: url, options: [.documentType: type], documentAttributes: nil)
            return cut(string.string, kind: kind, maxChars: maxChars)
        } catch {
            throw permission(error)
        }
    }

    static func pdf(_ url: URL, maxChars: Int) throws -> Read {
        guard FileManager.default.isReadableFile(atPath: url.path) else {
            throw permission(NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError))
        }
        guard let document = PDFDocument(url: url) else {
            throw ToolFailure("that PDF could not be opened")
        }
        if document.isLocked {
            throw ToolFailure("that PDF is locked with a password")
        }
        var parts: [String] = []
        var total = 0
        var stoppedEarly = false
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index)?.string, !page.isEmpty else { continue }
            parts.append(page)
            total += page.count
            if total > maxChars {
                stoppedEarly = index < document.pageCount - 1
                break
            }
        }
        let text = parts.joined(separator: "\n\n")
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw ToolFailure(
                "that PDF has no text in it, only pictures of pages (a scan). Open it and ask me to read the screen")
        }
        let read = cut(text, kind: "PDF", maxChars: maxChars)
        return Read(text: read.text, kind: "PDF", truncated: read.truncated || stoppedEarly, pages: document.pageCount)
    }

    static func cut(_ text: String, kind: String, maxChars: Int) -> Read {
        let normalized = text.replacingOccurrences(of: "\r\n", with: "\n")
        if normalized.count <= maxChars {
            return Read(text: normalized, kind: kind, truncated: false, pages: nil)
        }
        return Read(text: String(normalized.prefix(maxChars)), kind: kind, truncated: true, pages: nil)
    }
}
