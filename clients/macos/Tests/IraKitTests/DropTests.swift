import CryptoKit
import Foundation
import Testing
@testable import IraKit

@Suite("Drop")
struct DropTests {
    static let file: JSONValue = [
        "id": 42, "kind": "file", "text": "v2", "name": "plan.pdf", "mime": "application/pdf", "size": 3000,
        "sha256": "ab", "from_device_id": 7, "from_label": "Pixel 7",
    ]

    @Test func itemsAndFrames() throws {
        let item = try #require(DropItem(DropTests.file))
        #expect(item == DropItem(id: 42, kind: "file", text: "v2", name: "plan.pdf", mime: "application/pdf", size: 3000, sha256: "ab", fromDeviceID: 7, fromLabel: "Pixel 7"))
        #expect(item.preview == "plan.pdf (2.9 KB): v2")
        #expect(try DeviceProtocol.decode(#"{"type":"drop","event":"deleted","id":42}"#) == .drop(.deleted(42)))
        let new = try DeviceProtocol.decode(#"{"type":"drop","event":"new","item":{"id":5,"kind":"text","text":"hi","from_label":"Web"}}"#)
        #expect(new == .drop(.new(DropItem(id: 5, kind: "text", text: "hi", fromLabel: "Web"))))
        #expect(throws: DeviceProtocol.BadFrame.self) { try DeviceProtocol.decode(#"{"type":"drop","event":"new"}"#) }
    }

    @Test(arguments: ["javascript:alert(1)", "file:///etc/passwd", "https://a.example/x y", "ira://pair?code=x"])
    func onlyAPlainWebAddressOpens(text: String) {
        #expect(DropItem(id: 1, kind: "link", text: text).link == nil)
    }

    @Test func aLinkOpens() {
        #expect(DropItem(id: 1, kind: "link", text: " https://example.com/a ").link?.absoluteString == "https://example.com/a")
        #expect(DropItem(id: 1, kind: "text", text: "https://example.com/a").link == nil)
    }

    @Test func namesStayInTheFolderAndNeverOverwrite() throws {
        #expect(Drop.safeName("../../plan.pdf") == "plan.pdf")
        #expect(Drop.safeName("C:\\x\\evil.sh") == "evil.sh")
        #expect(Drop.safeName(" .. ") == "file")
        #expect(Drop.safeName("a\u{0}b\u{7f}") == "ab")
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        #expect(Drop.freeURL(in: folder, name: "plan.pdf").lastPathComponent == "plan.pdf")
        try Data("x".utf8).write(to: folder.appendingPathComponent("plan.pdf"))
        try Data("x".utf8).write(to: folder.appendingPathComponent("plan 2.pdf"))
        #expect(Drop.freeURL(in: folder, name: "plan.pdf").lastPathComponent == "plan 3.pdf")
    }

    @Test func sendListSaveDelete() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let source = folder.appendingPathComponent("notes \"q\".txt")
        let content = Data((0..<3000).map { UInt8($0 % 251) })
        try content.write(to: source)
        let hash = SHA256.hash(data: content).map { String(format: "%02x", $0) }.joined()
        let session = StubProtocol.session(host: "drop.example") { request, body in
            let path = request.url!.path
            if request.httpMethod == "GET", path == "/v1/me/drop" {
                return .init(status: 200, body: Data(#"{"items":[{"id":9,"kind":"text","text":"hi","from_label":"Web"}],"has_more":true}"#.utf8))
            }
            if request.httpMethod == "POST", path == "/v1/me/drop" {
                let text = String(decoding: body ?? Data(), as: UTF8.self)
                let kind = text.contains("filename=") ? "file" : "text"
                return .init(status: 201, body: Data(#"{"id":10,"kind":"\#(kind)","from_label":"Studio Mac"}"#.utf8))
            }
            if path == "/v1/me/drop/10/file" { return .init(status: 200, body: content) }
            if path == "/v1/me/drop/11/file" { return .init(status: 200, body: Data("tampered".utf8)) }
            if request.httpMethod == "DELETE" { return .init(status: path.hasSuffix("/404") ? 404 : 204, body: Data()) }
            return .init(status: 500, body: Data())
        }
        let client = DropClient(server: "https://drop.example", session: session, token: { "irad_x" })

        let page = try await client.list(after: 8)
        #expect(page.items.map(\.id) == [9] && page.hasMore)
        #expect(try await client.send(text: "call the CA").kind == "text")
        #expect(try await client.send(file: source, caption: "for Friday").kind == "file")

        let requests = StubProtocol.requests("drop.example")
        #expect(requests[0].0.url?.query == "limit=50&after_id=8")
        #expect(requests[0].0.value(forHTTPHeaderField: "Authorization") == "Bearer irad_x")
        let upload = try #require(requests.last)
        let type = try #require(upload.0.value(forHTTPHeaderField: "Content-Type"))
        let boundary = String(type.split(separator: "=").last!)
        let body = try #require(upload.1)
        #expect(upload.0.value(forHTTPHeaderField: "Content-Length") == String(body.count))
        let text = String(decoding: body, as: UTF8.self)
        #expect(text.hasPrefix("--\(boundary)\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\nfor Friday\r\n"))
        #expect(text.contains("filename=\"notes 'q'.txt\"\r\nContent-Type: text/plain"))
        #expect(body.range(of: content) != nil && text.hasSuffix("\r\n--\(boundary)--\r\n"))

        let downloads = folder.appendingPathComponent("Downloads/Ira")
        let saved = try await client.save(DropItem(id: 10, kind: "file", name: "../plan.bin", sha256: hash), into: downloads)
        #expect(saved.lastPathComponent == "plan.bin")
        #expect(try Data(contentsOf: saved) == content)
        #expect(try saved.resourceValues(forKeys: [.quarantinePropertiesKey]).quarantineProperties != nil)
        let again = try await client.save(DropItem(id: 10, kind: "file", name: "plan.bin", sha256: hash), into: downloads)
        #expect(again.lastPathComponent == "plan 2.bin")
        await #expect(throws: DropClient.Failure.self) {
            try await client.save(DropItem(id: 11, kind: "file", name: "x.bin", sha256: hash), into: downloads)
        }
        #expect(!FileManager.default.fileExists(atPath: downloads.appendingPathComponent("x.bin").path))

        try await client.delete(404)  // gone already: fine
    }
}
