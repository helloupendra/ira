import Foundation

/// The skills an iPhone can offer, each with the iOS permission it needs.
public enum Skill: String, CaseIterable, Sendable, Identifiable {
    case contacts, calendar, reminders, location, calls

    public var id: String { rawValue }

    /// The name on the checklist.
    public var title: String {
        switch self {
        case .contacts: return "Contacts"
        case .calendar: return "Calendar"
        case .reminders: return "Reminders"
        case .location: return "Location"
        case .calls: return "Calls"
        }
    }

    /// One line: why Ira asks, in plain words.
    public var reason: String {
        switch self {
        case .contacts: return "So Ira can put a name to a number, or find the number to call."
        case .calendar: return "So Ira can tell you what is on your day, and add an event after your yes."
        case .reminders: return "So Ira can list your reminders, add one, and tick one off."
        case .location: return "So Ira can say where you are, when you ask. Only while Ira is open."
        case .calls: return "So Ira can start a call after your yes. iOS still asks you to tap Call."
        }
    }

    /// Whether iOS has a permission prompt for it (calls have none: the tap is the permission).
    public var needsPermission: Bool { self != .calls }
}

/// Every tool this iPhone can offer Ira, as the hello lists them: name,
/// description, JSON Schema parameters, skill and tier.
///
/// Tiers (docs/devices.md): 0 reads; 1 small and undoable, Ira does it and says
/// so; 2 changes the calendar or reaches another person, so Ira reads it back
/// with its exact target and waits for a yes; 3 needs the PIN. The tier is fixed
/// here; the model cannot lower it. A skill is the grant the person switches on
/// for this iPhone with their PIN.
///
/// What iOS does not allow, so this app never offers it: reading the call log,
/// SMS or other apps' notifications, sending a message for you, and placing a
/// call without your tap.
public enum ToolCatalog {
    public struct Spec: Sendable, Equatable {
        public let name: String
        public let skill: Skill
        public let tier: Int
        public let definition: JSONValue
    }

    static func tool(_ name: String, skill: Skill, tier: Int, _ description: String,
                     properties: [String: JSONValue] = [:], required: [String] = []) -> Spec {
        var parameters: [String: JSONValue] = [
            "type": "object", "properties": .object(properties), "additionalProperties": false,
        ]
        if !required.isEmpty { parameters["required"] = .array(required.map { .string($0) }) }
        let definition: JSONValue = [
            "name": .string(name), "description": .string(description), "parameters": .object(parameters),
            "skill": .string(skill.rawValue), "tier": .number(Double(tier)),
        ]
        return Spec(name: name, skill: skill, tier: tier, definition: definition)
    }

    static func text(_ description: String, maxLength: Int? = nil) -> JSONValue {
        var field: [String: JSONValue] = ["type": "string", "description": .string(description)]
        if let maxLength { field["maxLength"] = .number(Double(maxLength)) }
        return .object(field)
    }

    static func integer(_ description: String, _ range: ClosedRange<Int>) -> JSONValue {
        ["type": "integer", "minimum": .number(Double(range.lowerBound)), "maximum": .number(Double(range.upperBound)),
         "description": .string(description)]
    }

    static let date = "A date (2026-10-23) or a local date and time (2026-10-23T14:30)."

    public static let all: [Spec] = [
        tool("contacts_lookup", skill: .contacts, tier: 0,
             "Look up people in this iPhone's contacts (iCloud, Google and Exchange accounts included) by name, phone number or email. Returns up to 10 with their numbers and emails. Use it to put a name to a number, or to find the number before a call.",
             properties: ["query": text("A name, a phone number (any format, or its last digits), or an email address.", maxLength: 100)],
             required: ["query"]),
        tool("calendar_read", skill: .calendar, tier: 0,
             "Read the events in this iPhone's calendars (iCloud, Google, Exchange): title, start, end, place and calendar. Today by default.",
             properties: [
                "from": text("The first day. \(date) Default: today.", maxLength: 25),
                "days": integer("How many days from then (default 1).", 1...31),
                "query": text("Only events whose title or place has these words.", maxLength: 100),
                "calendar": text("Only this calendar, by name.", maxLength: 80),
             ]),
        tool("calendar_add", skill: .calendar, tier: 2,
             "Add an event to a calendar on this iPhone. Give the exact title, start and calendar: they are read back to the person before it is added.",
             properties: [
                "title": text("The event's title.", maxLength: 200),
                "start": text("When it starts. \(date) A bare date makes an all-day event.", maxLength: 25),
                "end": text("When it ends. \(date)", maxLength: 25),
                "durationMinutes": integer("How long, if no end is given (default 60).", 5...1440),
                "allDay": ["type": "boolean", "description": "An all-day event."],
                "location": text("Where.", maxLength: 300),
                "notes": text("Notes on the event.", maxLength: 2000),
                "calendar": text("Which calendar, by name. Default: the iPhone's default calendar.", maxLength: 80),
             ], required: ["title", "start"]),
        tool("reminders_list", skill: .reminders, tier: 0,
             "List the reminders on this iPhone (Apple Reminders), open ones first by due date.",
             properties: [
                "list": text("Only this list, by name.", maxLength: 80),
                "includeDone": ["type": "boolean", "description": "Also the ones already done."],
                "query": text("Only reminders whose title has these words.", maxLength: 100),
             ]),
        tool("reminders_add", skill: .reminders, tier: 1,
             "Add a reminder in Apple Reminders on this iPhone, with a due time if given (the iPhone alerts then, even when Ira is closed). Say that you added it.",
             properties: [
                "title": text("What to be reminded of.", maxLength: 300),
                "due": text("When. \(date)", maxLength: 25),
                "list": text("Which list, by name. Default: the default list.", maxLength: 80),
                "notes": text("Notes.", maxLength: 2000),
             ], required: ["title"]),
        tool("reminders_done", skill: .reminders, tier: 1,
             "Mark a reminder as done, by its id from reminders_list or its exact title.",
             properties: ["id": text("The reminder's id.", maxLength: 200), "title": text("The reminder's exact title.", maxLength: 300)]),
        tool("location_now", skill: .location, tier: 0,
             "Where this iPhone is now: latitude, longitude, how accurate, and the address when the iPhone can tell. Read once when asked, only while Ira is open on the iPhone; the iPhone keeps nothing."),
        tool("call_place", skill: .calls, tier: 2,
             "Start a phone call from this iPhone. Give the exact number and, when known, the person's name: both are read back before anything happens. Then the iPhone shows its own Call prompt and the person taps Call; iOS lets no app call by itself. Only while Ira is open on the iPhone.",
             properties: [
                "number": text("The phone number to call: digits, with + and the country code if known.", maxLength: 24),
                "name": text("Who is being called, as the person knows them.", maxLength: 80),
             ], required: ["number"]),
    ]

    /// The hello's tools, in order.
    public static var definitions: [JSONValue] { all.map(\.definition) }

    public static func spec(_ name: String) -> Spec? { all.first { $0.name == name } }
}
