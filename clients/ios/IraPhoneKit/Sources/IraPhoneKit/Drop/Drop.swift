import CryptoKit
import Foundation

/// One item in the person's Drop (docs/api.md): text, a link or a file.
public struct DropItem: Equatable, Sendable, Identifiable {
    public let id: Int
    /// text, link or file.
    public let kind: String
    /// The text or link; a file's caption.
    public let text: String?
    public let name: String?
    public let mime: String?
    public let size: Int?
    public let sha256: String?
    public let fromDeviceID: Int?
    /// The device's name, or Web, CLI, Telegram, Ira.
    public let fromLabel: String

    public init(
        id: Int, kind: String, text: String? = nil, name: String? = nil, mime: String? = nil, size: Int? = nil,
        sha256: String? = nil, fromDeviceID: Int? = nil, fromLabel: String = ""
    ) {
        self.id = id
        self.kind = kind
        self.text = text
        self.name = name
        self.mime = mime
        self.size = size
        self.sha256 = sha256
        self.fromDeviceID = fromDeviceID
        self.fromLabel = fromLabel
    }

    public init?(_ json: JSONValue) {
        guard let id = json["id"]?.intValue, let kind = json["kind"]?.stringValue else { return nil }
        self.init(
            id: id, kind: kind, text: json["text"]?.stringValue, name: json["name"]?.stringValue,
            mime: json["mime"]?.stringValue, size: json["size"]?.intValue, sha256: json["sha256"]?.stringValue,
            fromDeviceID: json["from_device_id"]?.intValue, fromLabel: json["from_label"]?.stringValue ?? "")
    }

    public var isFile: Bool { kind == "file" }

    /// A link this iPhone may open: one http(s) address, nothing else.
    public var link: URL? {
        guard kind == "link", let text = text?.trimmingCharacters(in: .whitespacesAndNewlines),
            !text.contains(where: \.isWhitespace), let url = URL(string: text),
            ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil
        else { return nil }
        return url
    }

    /// One line for the menu or a notification: a file's name and size, or the text.
    public var preview: String {
        let words = (text ?? "").split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let line = isFile ? "\(Drop.safeName(name)) (\(Drop.size(size ?? 0)))" + (words.isEmpty ? "" : ": \(words)") : words
        return line.count <= 200 ? line : String(line.prefix(199)) + "…"
    }
}

/// A change in the Drop, from the device WebSocket: something new, or one deleted.
public enum DropFrame: Equatable, Sendable {
    case new(DropItem)
    case deleted(Int)
}

public enum Drop {
    public static let path = "/v1/me/drop"

    /// A file name safe to save: no folders, no control characters, never empty.
    public static func safeName(_ name: String?) -> String {
        let base = (name ?? "").replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
        let clean = String(base.unicodeScalars.filter { $0.value >= 0x20 && $0.value != 0x7F })
            .trimmingCharacters(in: CharacterSet(charactersIn: " ."))
        return clean.isEmpty ? "file" : String(clean.prefix(200))
    }

    /// Where a file goes in [folder]: its name, else "plan 2.pdf", "plan 3.pdf", as the Finder does.
    public static func freeURL(in folder: URL, name: String) -> URL {
        let first = folder.appendingPathComponent(name)
        guard FileManager.default.fileExists(atPath: first.path) else { return first }
        let stem = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var number = 2
        while true {
            let candidate = folder.appendingPathComponent(ext.isEmpty ? "\(stem) \(number)" : "\(stem) \(number).\(ext)")
            if !FileManager.default.fileExists(atPath: candidate.path) { return candidate }
            number += 1
        }
    }

    public static func size(_ bytes: Int) -> String {
        if bytes < 1024 { return "\(bytes) B" }
        if bytes < 1024 * 1024 { return String(format: "%.1f KB", Double(bytes) / 1024) }
        return String(format: "%.1f MB", Double(bytes) / 1024 / 1024)
    }

    /// A multipart body for one file (and a caption), written to [out] a megabyte at a time.
    static func writeMultipart(file: URL, name: String, mime: String, caption: String?, boundary: String, to out: URL) throws {
        FileManager.default.createFile(atPath: out.path, contents: nil)
        let sink = try FileHandle(forWritingTo: out)
        defer { try? sink.close() }
        func write(_ text: String) throws { try sink.write(contentsOf: Data(text.utf8)) }
        if let caption, !caption.isEmpty {
            try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n\(caption)\r\n")
        }
        let quoted = name.replacingOccurrences(of: "\"", with: "'").replacingOccurrences(of: "\r", with: "")
            .replacingOccurrences(of: "\n", with: "")
        try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(quoted)\"\r\nContent-Type: \(mime)\r\n\r\n")
        let source = try FileHandle(forReadingFrom: file)
        defer { try? source.close() }
        while let chunk = try source.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            try sink.write(contentsOf: chunk)
        }
        try write("\r\n--\(boundary)--\r\n")
    }

    static func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hash = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            hash.update(data: chunk)
        }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func mime(for file: URL) -> String {
        if let type = try? file.resourceValues(forKeys: [.contentTypeKey]).contentType, let mime = type.preferredMIMEType {
            return mime
        }
        return "application/octet-stream"
    }
}

/// The Drop's HTTP API with this iPhone's device token: list, send, delete, and save a file.
public final class DropClient: @unchecked Sendable {
    public struct Failure: LocalizedError, Equatable {
        public let message: String
        public let status: Int?
        public init(_ message: String, status: Int? = nil) {
            self.message = message
            self.status = status
        }
        public var errorDescription: String? { message }
    }

    public let server: String
    private let session: URLSession
    private let token: @Sendable () -> String?

    public init(server: String, session: URLSession = .shared, token: @escaping @Sendable () -> String?) {
        self.server = server
        self.session = session
        self.token = token
    }

    private func request(_ path: String, method: String = "GET", timeout: TimeInterval = 60) throws -> URLRequest {
        guard let url = URL(string: server + path) else { throw Failure("bad server address") }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue(IraPhone.userAgent, forHTTPHeaderField: "User-Agent")
        if let token = token() { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return request
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw Failure("could not reach \(server): \(Pairing.reason(error))")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw DropClient.failure(data, status: status) }
        return data
    }

    static func failure(_ data: Data, status: Int) -> Failure {
        switch status {
        case 401: return Failure("your Ira did not accept this iPhone: pair it again", status: status)
        case 403: return Failure("your account on this Ira cannot use Drop", status: status)
        default: return Failure(AskClient.detail(data, status: status), status: status)
        }
    }

    /// Newest first: the latest page, the items after one (to catch up) or before one (older).
    public func list(after: Int? = nil, before: Int? = nil, limit: Int = 50) async throws -> (items: [DropItem], hasMore: Bool) {
        var query = ["limit=\(limit)"]
        if let after { query.append("after_id=\(after)") }
        if let before { query.append("before_id=\(before)") }
        let body = JSONValue.parse(try await send(try request(Drop.path + "?" + query.joined(separator: "&"))))
        let items = (body?["items"]?.arrayValue ?? []).compactMap(DropItem.init)
        return (items, body?["has_more"]?.boolValue ?? false)
    }

    public func send(text: String) async throws -> DropItem {
        var request = try request(Drop.path, method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data(JSONValue.object(["text": .string(text)]).encoded().utf8)
        guard let item = JSONValue.parse(try await send(request)).flatMap(DropItem.init) else {
            throw Failure("the server's answer was not an item")
        }
        return item
    }

    /// Send a file, read from disk as it goes (through a multipart copy, so never all in memory).
    public func send(file: URL, caption: String? = nil) async throws -> DropItem {
        let boundary = "ira-\(UUID().uuidString)"
        let body = FileManager.default.temporaryDirectory.appendingPathComponent("ira-drop-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: body) }
        do {
            try Drop.writeMultipart(
                file: file, name: Drop.safeName(file.lastPathComponent), mime: Drop.mime(for: file), caption: caption,
                boundary: boundary, to: body)
        } catch {
            throw Failure("\(file.lastPathComponent) could not be read")
        }
        let length = (try? FileManager.default.attributesOfItem(atPath: body.path)[.size] as? Int) ?? 0
        var request = try request(Drop.path, method: "POST", timeout: 300)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.setValue(String(length), forHTTPHeaderField: "Content-Length")
        request.httpBodyStream = InputStream(url: body)
        guard let item = JSONValue.parse(try await send(request)).flatMap(DropItem.init) else {
            throw Failure("the server's answer was not an item")
        }
        return item
    }

    public func delete(_ id: Int) async throws {
        do {
            _ = try await send(try request("\(Drop.path)/\(id)", method: "DELETE"))
        } catch let failure as Failure where failure.status == 404 {
            return  // gone already
        }
    }

    /// Save a file into [folder] (made if needed), checked against its SHA-256. Returns where
    /// it went: the app hands it on from there (Save to Files, Open In).
    public func save(_ item: DropItem, into folder: URL) async throws -> URL {
        let downloaded: URL
        let response: URLResponse
        do {
            (downloaded, response) = try await session.download(for: try request("\(Drop.path)/\(item.id)/file", timeout: 300))
        } catch let failure as Failure {
            throw failure
        } catch {
            throw Failure("could not reach \(server): \(Pairing.reason(error))")
        }
        defer { try? FileManager.default.removeItem(at: downloaded) }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw DropClient.failure((try? Data(contentsOf: downloaded)) ?? Data(), status: status)
        }
        if let expected = item.sha256, (try? Drop.sha256(of: downloaded)) != expected {
            throw Failure("the download did not match the file: try again")
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let target = Drop.freeURL(in: folder, name: Drop.safeName(item.name))
        try FileManager.default.moveItem(at: downloaded, to: target)
        return target
    }
}
