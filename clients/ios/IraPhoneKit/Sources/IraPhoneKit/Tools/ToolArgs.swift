import Foundation

/// A tool call's arguments, checked: the model wrote them, so nothing is trusted.
public struct ToolArgs {
    public let values: [String: JSONValue]

    public init(_ args: JSONValue, allowed: Set<String>) throws {
        guard let values = args.objectValue else { throw ToolFailure("arguments must be an object") }
        let unknown = Set(values.keys).subtracting(allowed).sorted()
        if !unknown.isEmpty {
            throw ToolFailure("unknown argument(s): \(unknown.joined(separator: ", "))")
        }
        self.values = values
    }

    /// Text, trimmed and cut to `limit`; nil when missing or empty.
    public func text(_ name: String, limit: Int = 500) throws -> String? {
        guard let value = values[name], !value.isNull else { return nil }
        guard let text = value.stringValue else { throw ToolFailure("\(name) must be text") }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : String(trimmed.prefix(limit))
    }

    /// Text that must be there.
    public func required(_ name: String, limit: Int = 500, what: String? = nil) throws -> String {
        guard let text = try text(name, limit: limit) else {
            throw ToolFailure("say \(what ?? "the \(name)")")
        }
        return text
    }

    /// A whole number, held to `range`.
    public func number(_ name: String, _ range: ClosedRange<Int>) throws -> Int? {
        guard let value = values[name], !value.isNull else { return nil }
        guard let number = value.doubleValue, number.isFinite else { throw ToolFailure("\(name) must be a number") }
        return min(max(Int(number), range.lowerBound), range.upperBound)
    }

    public func bool(_ name: String) throws -> Bool? {
        guard let value = values[name], !value.isNull else { return nil }
        guard let flag = value.boolValue else { throw ToolFailure("\(name) must be true or false") }
        return flag
    }

    /// A list of text, from a JSON list or one comma-separated string.
    public func list(_ name: String, limit: Int = 20) throws -> [String] {
        guard let value = values[name], !value.isNull else { return [] }
        let items: [String]
        if let text = value.stringValue {
            items = text.split(separator: ",").map(String.init)
        } else if let array = value.arrayValue {
            items = try array.map {
                guard let text = $0.stringValue else { throw ToolFailure("\(name) must be text") }
                return text
            }
        } else {
            throw ToolFailure("\(name) must be text or a list")
        }
        return items.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }.prefix(limit).map { $0 }
    }
}

/// Dates as people and models write them, in this iPhone's time zone.
public enum LocalDate {
    /// "2026-10-23", "2026-10-23T09:30", "2026-10-23 09:30:00", or with an offset
    /// ("...Z", "...+05:30"). `hasTime` is false for a bare day.
    public static func parse(_ text: String, timeZone: TimeZone = .current) -> (date: Date, hasTime: Bool)? {
        let text = text.trimmingCharacters(in: .whitespaces)
        let pattern = #"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
            let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text))
        else { return nil }
        func group(_ index: Int) -> String? {
            Range(match.range(at: index), in: text).map { String(text[$0]) }
        }
        var components = DateComponents()
        components.year = Int(group(1)!)
        components.month = Int(group(2)!)
        components.day = Int(group(3)!)
        let hasTime = group(4) != nil
        components.hour = Int(group(4) ?? "0")
        components.minute = Int(group(5) ?? "0")
        components.second = Int(group(6) ?? "0")
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        if let offset = group(7) {
            if offset == "Z" {
                calendar.timeZone = TimeZone(secondsFromGMT: 0)!
            } else {
                let sign = offset.hasPrefix("-") ? -1 : 1
                let digits = offset.dropFirst().replacingOccurrences(of: ":", with: "")
                let hours = Int(digits.prefix(2)) ?? 0
                let minutes = Int(digits.suffix(2)) ?? 0
                calendar.timeZone = TimeZone(secondsFromGMT: sign * (hours * 3600 + minutes * 60))!
            }
        }
        guard let month = components.month, (1...12).contains(month),
            let day = components.day, (1...31).contains(day),
            let hour = components.hour, (0...23).contains(hour),
            let minute = components.minute, (0...59).contains(minute),
            let date = calendar.date(from: components),
            calendar.component(.day, from: date) == day
        else { return nil }
        return (date, hasTime)
    }

    /// A local timestamp with its offset: "2026-10-23T09:30:00+05:30".
    public static func iso(_ date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.timeZone = timeZone
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    /// "Thu 23 Oct, 09:30", for summaries Ira may read out.
    public static func spoken(_ date: Date, withTime: Bool = true, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_GB")
        formatter.timeZone = timeZone
        formatter.dateFormat = withTime ? "EEE d MMM, HH:mm" : "EEE d MMM"
        return formatter.string(from: date)
    }

    public static func time(_ date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_GB")
        formatter.timeZone = timeZone
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }
}
