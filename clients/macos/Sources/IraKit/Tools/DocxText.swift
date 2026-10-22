import Compression
import Foundation

/// The text of a Word document (.docx): its `word/document.xml`, without the markup.
///
/// A .docx is a ZIP archive. This reads the one entry it needs with a small ZIP
/// reader (stored or deflated entries, no ZIP64) and Apple's Compression
/// framework, and refuses an entry that would unpack past `maxUnpacked`, so a
/// crafted file cannot fill memory.
public enum DocxText {
    public static let maxUnpacked = 32 * 1024 * 1024

    public static func extract(from data: Data) throws -> String {
        let xml = try ZipArchive(data: data).entry(named: "word/document.xml", limit: maxUnpacked)
        return try text(fromDocumentXML: xml)
    }

    /// Paragraphs as lines, tabs as tabs, breaks as new lines; everything else dropped.
    public static func text(fromDocumentXML xml: Data) throws -> String {
        let reader = WordXMLReader()
        let parser = XMLParser(data: xml)
        parser.shouldResolveExternalEntities = false
        parser.delegate = reader
        guard parser.parse() else {
            throw ToolFailure("that Word document's text could not be read")
        }
        return reader.text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private final class WordXMLReader: NSObject, XMLParserDelegate {
    var text = ""
    private var inText = false

    func parser(
        _ parser: XMLParser, didStartElement name: String, namespaceURI: String?,
        qualifiedName: String?, attributes: [String: String] = [:]
    ) {
        switch name {
        case "w:t": inText = true
        case "w:tab": text += "\t"
        case "w:br", "w:cr": text += "\n"
        default: break
        }
    }

    func parser(
        _ parser: XMLParser, didEndElement name: String, namespaceURI: String?,
        qualifiedName: String?
    ) {
        switch name {
        case "w:t": inText = false
        case "w:p": text += "\n"
        default: break
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if inText { text += string }
    }
}

/// Just enough of the ZIP format to read one named entry.
struct ZipArchive {
    let data: Data

    init(data: Data) throws {
        guard data.count >= 22 else { throw ToolFailure("that is not a Word document (.docx)") }
        self.data = data
    }

    private func u16(_ offset: Int) -> Int {
        guard offset >= 0, offset + 2 <= data.count else { return 0 }
        let start = data.startIndex + offset
        return Int(data[start]) | Int(data[start + 1]) << 8
    }

    private func u32(_ offset: Int) -> Int {
        guard offset >= 0, offset + 4 <= data.count else { return 0 }
        return u16(offset) | u16(offset + 2) << 16
    }

    /// The end-of-central-directory record, searched for from the end.
    private func endRecord() throws -> Int {
        let lowest = max(0, data.count - 22 - 65_535)
        var offset = data.count - 22
        while offset >= lowest {
            if u32(offset) == 0x0605_4b50 { return offset }
            offset -= 1
        }
        throw ToolFailure("that is not a Word document (.docx)")
    }

    func entry(named wanted: String, limit: Int) throws -> Data {
        let end = try endRecord()
        let count = u16(end + 10)
        var offset = u32(end + 16)
        for _ in 0..<count {
            guard u32(offset) == 0x0201_4b50 else { break }
            let method = u16(offset + 10)
            let packed = u32(offset + 20)
            let unpacked = u32(offset + 24)
            let nameLength = u16(offset + 28)
            let extraLength = u16(offset + 30)
            let commentLength = u16(offset + 32)
            let local = u32(offset + 42)
            let nameStart = offset + 46
            guard nameStart + nameLength <= data.count else { break }
            let name = String(decoding: data.subdata(in: (data.startIndex + nameStart)..<(data.startIndex + nameStart + nameLength)), as: UTF8.self)
            if name == wanted {
                return try read(local: local, method: method, packed: packed, unpacked: unpacked, limit: limit)
            }
            offset = nameStart + nameLength + extraLength + commentLength
        }
        throw ToolFailure("that Word document has no text part")
    }

    private func read(local: Int, method: Int, packed: Int, unpacked: Int, limit: Int) throws -> Data {
        guard u32(local) == 0x0403_4b50 else { throw ToolFailure("that Word document is damaged") }
        if packed == 0xFFFF_FFFF || unpacked == 0xFFFF_FFFF {
            throw ToolFailure("that Word document is too large to read")
        }
        guard unpacked <= limit else { throw ToolFailure("that Word document is too large to read") }
        let start = local + 30 + u16(local + 26) + u16(local + 28)
        guard start >= 0, start + packed <= data.count else {
            throw ToolFailure("that Word document is damaged")
        }
        let body = data.subdata(in: (data.startIndex + start)..<(data.startIndex + start + packed))
        switch method {
        case 0:
            return body
        case 8:
            return try inflate(body, size: unpacked)
        default:
            throw ToolFailure("that Word document uses a compression this app cannot read")
        }
    }

    /// Raw DEFLATE (RFC 1951), which is what Compression's ZLIB algorithm reads.
    private func inflate(_ body: Data, size: Int) throws -> Data {
        if size == 0 { return Data() }
        var output = Data(count: size)
        let written = output.withUnsafeMutableBytes { (out: UnsafeMutableRawBufferPointer) -> Int in
            body.withUnsafeBytes { (input: UnsafeRawBufferPointer) -> Int in
                guard let outBase = out.bindMemory(to: UInt8.self).baseAddress,
                    let inBase = input.bindMemory(to: UInt8.self).baseAddress
                else { return 0 }
                return compression_decode_buffer(
                    outBase, size, inBase, body.count, nil, COMPRESSION_ZLIB)
            }
        }
        guard written == size else { throw ToolFailure("that Word document is damaged") }
        return output
    }
}
