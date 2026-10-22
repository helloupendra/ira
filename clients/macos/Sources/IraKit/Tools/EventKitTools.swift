import EventKit
import Foundation

/// The calendars and reminder lists on this Mac, through EventKit: iCloud,
/// Google and Exchange accounts added to the Mac all count, with no sign-in.
///
/// * `calendar_read` (Tier 0), `calendar_add` (Tier 2: it changes the calendar);
/// * `reminders_list` (Tier 0), `reminders_set` (Tier 1: add one, or mark one done).
public final class EventKitTools: @unchecked Sendable {
    private let store = EKEventStore()
    private let timeZone: TimeZone

    public init(timeZone: TimeZone = .current) {
        self.timeZone = timeZone
    }

    static func deniedMessage(_ type: EKEntityType) -> String {
        type == .event
            ? "Calendars are off for Ira. Allow Ira in System Settings → Privacy & Security → Calendars (Full Access), then ask again"
            : "Reminders are off for Ira. Allow Ira in System Settings → Privacy & Security → Reminders (Full Access), then ask again"
    }

    func ensureAccess(_ type: EKEntityType) async throws {
        switch EKEventStore.authorizationStatus(for: type) {
        case .fullAccess, .authorized: return
        case .notDetermined:
            let granted: Bool
            do {
                granted = type == .event
                    ? try await store.requestFullAccessToEvents()
                    : try await store.requestFullAccessToReminders()
            } catch {
                granted = false
            }
            if !granted { throw ToolFailure(EventKitTools.deniedMessage(type)) }
        default:
            throw ToolFailure(EventKitTools.deniedMessage(type))
        }
    }

    static func date(_ text: String?, name: String) throws -> (date: Date, hasTime: Bool)? {
        guard let text else { return nil }
        guard let parsed = LocalDate.parse(text) else {
            throw ToolFailure("\(name) must be a date like 2026-10-23 or 2026-10-23T14:30")
        }
        return parsed
    }

    private func calendar(named name: String?, for type: EKEntityType) throws -> EKCalendar? {
        guard let name else { return nil }
        let all = store.calendars(for: type)
        if let exact = all.first(where: { $0.title.caseInsensitiveCompare(name) == .orderedSame }) { return exact }
        if let partial = all.first(where: { $0.title.localizedCaseInsensitiveContains(name) }) { return partial }
        let names = all.map(\.title).sorted().joined(separator: ", ")
        throw ToolFailure("there is no \(type == .event ? "calendar" : "list") called \(name); there are: \(names)")
    }

    // MARK: Calendar

    public func calendarRead(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["from", "days", "query", "calendar"])
        try await ensureAccess(.event)
        var day = Calendar(identifier: .gregorian)
        day.timeZone = timeZone
        let start = try EventKitTools.date(try args.text("from"), name: "from")?.date ?? day.startOfDay(for: Date())
        let days = try args.number("days", 1...31) ?? 1
        let end = day.date(byAdding: .day, value: days, to: day.startOfDay(for: start)) ?? start.addingTimeInterval(86_400)
        let calendars = try calendar(named: try args.text("calendar"), for: .event).map { [$0] }
        let query = try args.text("query", limit: 100)
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
        var events = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }
        if let query {
            events = events.filter {
                ($0.title ?? "").localizedCaseInsensitiveContains(query) || ($0.location ?? "").localizedCaseInsensitiveContains(query)
            }
        }
        let shown = events.prefix(50)
        let items: [JSONValue] = shown.map { event in
            var item: [String: JSONValue] = [
                "id": .string(event.eventIdentifier ?? ""),
                "title": .string(event.title ?? "Untitled"),
                "start": .string(LocalDate.iso(event.startDate, timeZone: timeZone)),
                "end": .string(LocalDate.iso(event.endDate, timeZone: timeZone)),
                "allDay": .bool(event.isAllDay),
                "calendar": .string(event.calendar.title),
            ]
            if let location = event.location, !location.isEmpty { item["location"] = .string(location) }
            return .object(item)
        }
        let summary: String
        if shown.isEmpty {
            summary = "Nothing on the calendar \(days == 1 ? "that day" : "in those \(days) days")."
        } else {
            let lines = shown.prefix(8).map { event in
                (event.isAllDay ? "all day" : LocalDate.time(event.startDate, timeZone: timeZone)) + " " + (event.title ?? "Untitled")
            }
            summary = "\(shown.count) event\(shown.count == 1 ? "" : "s"): " + lines.joined(separator: "; ") + "."
        }
        return ["events": .array(items), "count": .number(Double(shown.count)), "summary": .string(summary)]
    }

    public func calendarAdd(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["title", "start", "end", "durationMinutes", "allDay", "location", "notes", "calendar"])
        let title = try args.required("title", limit: 200, what: "what the event is (title)")
        guard let start = try EventKitTools.date(try args.text("start"), name: "start") else {
            throw ToolFailure("say when it starts (start), e.g. 2026-10-23T14:30")
        }
        let allDay = try args.bool("allDay") ?? !start.hasTime
        let end: Date
        if let given = try EventKitTools.date(try args.text("end"), name: "end") {
            end = given.date
        } else if allDay {
            end = start.date.addingTimeInterval(86_400)
        } else {
            end = start.date.addingTimeInterval(Double(try args.number("durationMinutes", 5...1440) ?? 60) * 60)
        }
        guard end > start.date else { throw ToolFailure("the end must be after the start") }
        try await ensureAccess(.event)
        let event = EKEvent(eventStore: store)
        event.title = title
        event.startDate = start.date
        event.endDate = end
        event.isAllDay = allDay
        event.location = try args.text("location", limit: 300)
        event.notes = try args.text("notes", limit: 2000)
        guard let target = try calendar(named: try args.text("calendar"), for: .event) ?? store.defaultCalendarForNewEvents else {
            throw ToolFailure("this Mac has no calendar to add events to")
        }
        guard target.allowsContentModifications else { throw ToolFailure("the calendar \(target.title) is read-only") }
        event.calendar = target
        do {
            try store.save(event, span: .thisEvent, commit: true)
        } catch {
            throw ToolFailure("the calendar did not save it: \(error.localizedDescription)")
        }
        let when = allDay
            ? LocalDate.spoken(start.date, withTime: false, timeZone: timeZone)
            : "\(LocalDate.spoken(start.date, timeZone: timeZone))–\(LocalDate.time(end, timeZone: timeZone))"
        return [
            "id": .string(event.eventIdentifier ?? ""),
            "summary": .string("Added “\(title)” on \(when) to \(target.title)."),
        ]
    }

    // MARK: Reminders

    private func fetchReminders(_ predicate: NSPredicate) async -> [EKReminder] {
        await withCheckedContinuation { continuation in
            store.fetchReminders(matching: predicate) { reminders in
                continuation.resume(returning: reminders ?? [])
            }
        }
    }

    private func view(_ reminder: EKReminder) -> JSONValue {
        var item: [String: JSONValue] = [
            "id": .string(reminder.calendarItemIdentifier),
            "title": .string(reminder.title ?? "Untitled"),
            "list": .string(reminder.calendar.title),
            "done": .bool(reminder.isCompleted),
        ]
        if let due = reminder.dueDateComponents, let date = Calendar.current.date(from: due) {
            item["due"] = .string(LocalDate.iso(date, timeZone: timeZone))
        }
        if let notes = reminder.notes, !notes.isEmpty { item["notes"] = .string(String(notes.prefix(300))) }
        return .object(item)
    }

    public func remindersList(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["list", "includeDone", "query"])
        try await ensureAccess(.reminder)
        let lists = try calendar(named: try args.text("list"), for: .reminder).map { [$0] }
        let predicate = try args.bool("includeDone") == true
            ? store.predicateForReminders(in: lists)
            : store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: lists)
        var reminders = await fetchReminders(predicate)
        if let query = try args.text("query", limit: 100) {
            reminders = reminders.filter { ($0.title ?? "").localizedCaseInsensitiveContains(query) }
        }
        reminders.sort { a, b in
            let da = a.dueDateComponents.flatMap { Calendar.current.date(from: $0) } ?? .distantFuture
            let db = b.dueDateComponents.flatMap { Calendar.current.date(from: $0) } ?? .distantFuture
            return da < db
        }
        let shown = Array(reminders.prefix(50))
        let summary = shown.isEmpty
            ? "No reminders."
            : "\(shown.count) reminder\(shown.count == 1 ? "" : "s"): " + shown.prefix(8).map { $0.title ?? "Untitled" }.joined(separator: "; ") + "."
        return ["reminders": .array(shown.map(view)), "count": .number(Double(shown.count)), "summary": .string(summary)]
    }

    public func remindersAdd(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["title", "due", "list", "notes"])
        let title = try args.required("title", limit: 300, what: "what to be reminded of (title)")
        let due = try EventKitTools.date(try args.text("due"), name: "due")
        try await ensureAccess(.reminder)
        let reminder = EKReminder(eventStore: store)
        reminder.title = title
        reminder.notes = try args.text("notes", limit: 2000)
        guard let list = try calendar(named: try args.text("list"), for: .reminder) ?? store.defaultCalendarForNewReminders() else {
            throw ToolFailure("this Mac has no reminder list")
        }
        reminder.calendar = list
        if let due {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = timeZone
            let units: Set<Calendar.Component> = due.hasTime ? [.year, .month, .day, .hour, .minute] : [.year, .month, .day]
            reminder.dueDateComponents = calendar.dateComponents(units, from: due.date)
            if due.hasTime { reminder.addAlarm(EKAlarm(absoluteDate: due.date)) }
        }
        do {
            try store.save(reminder, commit: true)
        } catch {
            throw ToolFailure("Reminders did not save it: \(error.localizedDescription)")
        }
        let when = due.map { " for \(LocalDate.spoken($0.date, withTime: $0.hasTime, timeZone: timeZone))" } ?? ""
        return ["id": .string(reminder.calendarItemIdentifier), "summary": .string("Added the reminder “\(title)”\(when) to \(list.title).")]
    }

    public func remindersDone(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "title"])
        let id = try args.text("id", limit: 200)
        let title = try args.text("title", limit: 300)
        guard id != nil || title != nil else { throw ToolFailure("say which reminder: its id or its title") }
        try await ensureAccess(.reminder)
        var reminder: EKReminder?
        if let id { reminder = store.calendarItem(withIdentifier: id) as? EKReminder }
        if reminder == nil, let title {
            let open = await fetchReminders(store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: nil))
            let matches = open.filter { ($0.title ?? "").caseInsensitiveCompare(title) == .orderedSame }
            if matches.count > 1 { throw ToolFailure("\(matches.count) open reminders are called \(title); say which by its id") }
            reminder = matches.first
        }
        guard let reminder else { throw ToolFailure("no open reminder matches that") }
        reminder.isCompleted = true
        do {
            try store.save(reminder, commit: true)
        } catch {
            throw ToolFailure("Reminders did not save it: \(error.localizedDescription)")
        }
        return ["id": .string(reminder.calendarItemIdentifier), "summary": .string("Marked “\(reminder.title ?? "the reminder")” as done.")]
    }
}
