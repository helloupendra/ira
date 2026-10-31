import Foundation
import UniformTypeIdentifiers

/// The Drop as the window lists it: newest first, under Today, Yesterday and older dates,
/// each item with an icon for its kind and one line saying where it came from, when and how big.
public enum DropList {
    public struct Section: Equatable, Identifiable {
        public let title: String
        public let items: [DropItem]
        public var id: String { title }
    }

    public static func sections(_ items: [DropItem], now: Date = Date(), calendar: Calendar = .current) -> [Section] {
        var sections: [Section] = []
        for item in items.sorted(by: { $0.id > $1.id }) {
            let title = day(item.createdAt, now: now, calendar: calendar)
            if sections.last?.title == title {
                sections[sections.count - 1] = Section(title: title, items: sections[sections.count - 1].items + [item])
            } else {
                sections.append(Section(title: title, items: [item]))
            }
        }
        return sections
    }

    static func day(_ date: Date?, now: Date, calendar: Calendar) -> String {
        guard let date else { return "Earlier" }
        if calendar.isDate(date, inSameDayAs: now) { return "Today" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return "Yesterday"
        }
        var style = Date.FormatStyle(date: .abbreviated, time: .omitted)
        style.calendar = calendar
        style.timeZone = calendar.timeZone
        return date.formatted(style)
    }

    /// An SF Symbol for the item's kind: a link, text, or the file's type.
    public static func symbol(_ item: DropItem) -> String {
        switch item.kind {
        case "link": return "link"
        case "file": break
        default: return "text.alignleft"
        }
        let type = item.mime.flatMap { UTType(mimeType: $0) }
            ?? UTType(filenameExtension: (Drop.safeName(item.name) as NSString).pathExtension)
        guard let type else { return "doc" }
        if type.conforms(to: .image) { return "photo" }
        if type.conforms(to: .pdf) { return "doc.richtext" }
        if type.conforms(to: .movie) { return "film" }
        if type.conforms(to: .audio) { return "waveform" }
        if type.conforms(to: .archive) { return "doc.zipper" }
        return "doc"
    }

    /// The item's main line: a file's name, else its text on one line.
    public static func title(_ item: DropItem) -> String {
        if item.isFile { return Drop.safeName(item.name) }
        return (item.text ?? "").split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    /// "From Pixel 7 · 10:42 · 2.9 KB"
    public static func detail(_ item: DropItem, calendar: Calendar = .current) -> String {
        var parts = ["From \(item.fromLabel.isEmpty ? "a device" : item.fromLabel)"]
        if let date = item.createdAt {
            var style = Date.FormatStyle(date: .omitted, time: .shortened)
            style.calendar = calendar
            style.timeZone = calendar.timeZone
            parts.append(date.formatted(style))
        }
        if item.isFile, let size = item.size { parts.append(Drop.size(size)) }
        if item.isFile, let caption = item.text?.trimmingCharacters(in: .whitespacesAndNewlines), !caption.isEmpty {
            parts.append(caption)
        }
        return parts.joined(separator: " · ")
    }
}
