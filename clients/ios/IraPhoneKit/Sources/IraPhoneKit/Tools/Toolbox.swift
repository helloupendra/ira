import Foundation

/// One thing Ira used on this iPhone, for the "What Ira used" list: the tool and
/// how it ended, never what it read.
public struct Activity: Equatable, Identifiable, Sendable {
    public let id: UUID
    public let at: Date
    public let tool: String
    public let ok: Bool

    public init(at: Date = Date(), tool: String, ok: Bool) {
        self.id = UUID()
        self.at = at
        self.tool = tool
        self.ok = ok
    }

    /// What the tool did, in words.
    public var verb: String {
        switch tool {
        case "contacts_lookup": return "Looked up a contact"
        case "calendar_read": return "Read your calendar"
        case "calendar_add": return "Added an event"
        case "reminders_list": return "Read your reminders"
        case "reminders_add": return "Added a reminder"
        case "reminders_done": return "Completed a reminder"
        case "location_now": return "Read where you are"
        case "call_place": return "Asked to start a call"
        default: return tool
        }
    }
}

/// The tools this iPhone offers Ira (`ToolCatalog` lists them with their skills
/// and tiers): each call is checked against iOS's permission for its skill,
/// held to a deadline under the server's 25 seconds, and recorded by name.
///
/// Everything a tool returns reaches the model marked untrusted by the server:
/// it is data, never instructions.
public final class Toolbox: ToolRunner, @unchecked Sendable {
    public typealias Opener = @Sendable (URL) async -> Bool

    private let permissions: PermissionProvider
    private let eventKit: EventKitTools
    private let opener: Opener
    private let foreground: @Sendable () async -> Bool
    private let record: @Sendable (Activity) -> Void
    private let log: IraLog
    /// Tools that never reach iOS: for tests.
    private let stand: (@Sendable (String, JSONValue) async throws -> JSONValue)?
    private let deadlines: @Sendable (String) -> Double

    public init(
        permissions: PermissionProvider,
        eventKit: EventKitTools,
        opener: @escaping Opener,
        foreground: @escaping @Sendable () async -> Bool,
        log: IraLog = .shared,
        stand: (@Sendable (String, JSONValue) async throws -> JSONValue)? = nil,
        deadlines: @escaping @Sendable (String) -> Double = Toolbox.deadline(for:),
        record: @escaping @Sendable (Activity) -> Void = { _ in }
    ) {
        self.deadlines = deadlines
        self.permissions = permissions
        self.eventKit = eventKit
        self.opener = opener
        self.foreground = foreground
        self.log = log
        self.stand = stand
        self.record = record
    }

    public var definitions: [JSONValue] { ToolCatalog.definitions }

    /// How long a tool may take on this iPhone: always under the server's 25 seconds,
    /// so a stuck tool answers with a reason instead of leaving Ira waiting.
    public static func deadline(for name: String) -> Double {
        switch name {
        case "location_now": return 20
        case "contacts_lookup": return 12
        default: return 10
        }
    }

    public func call(_ name: String, args: JSONValue) async throws -> JSONValue {
        guard let spec = ToolCatalog.spec(name) else {
            throw ToolFailure("this iPhone has no tool called \(name)")
        }
        do {
            try await gate(spec.skill)
            let result = try await withTimeout(deadlines(name)) { [self] in
                try await self.run(name, args)
            }
            record(Activity(tool: name, ok: true))
            return result
        } catch is TimedOut {
            record(Activity(tool: name, ok: false))
            throw ToolFailure("that took too long on the iPhone. If the iPhone is showing a question, answer it, then ask again")
        } catch {
            record(Activity(tool: name, ok: false))
            throw error
        }
    }

    /// iOS must allow the skill's permission. Its prompt shows only while Ira is on
    /// screen; otherwise Ira is told what the person needs to do.
    func gate(_ skill: Skill) async throws {
        var state = permissions.state(.skill(skill))
        if state == .notAsked {
            guard await foreground() else {
                throw ToolFailure("Ira has not asked for \(skill.title) on the iPhone yet. Open Ira on the iPhone and allow \(skill.title) on its checklist, then ask again")
            }
            state = await permissions.request(.skill(skill))
        }
        switch state {
        case .allowed:
            return
        case .notAsked, .denied:
            throw ToolFailure("\(skill.title) is off for Ira on the iPhone. Switch it on in the iPhone's Settings, Ira, \(skill.title) (Ira's checklist has a button for it), then ask again")
        case .restricted:
            throw ToolFailure("Screen Time or a profile on this iPhone does not allow \(skill.title) for any app")
        case .partial(let why):
            throw ToolFailure("\(why) Change it in the iPhone's Settings, Ira, \(skill.title), then ask again")
        }
    }

    private func run(_ name: String, _ args: JSONValue) async throws -> JSONValue {
        if let stand { return try await stand(name, args) }
        switch name {
        case "contacts_lookup":
            let checked = try ToolArgs(args, allowed: ["query"])
            return try await ContactsTool.lookup(try checked.required("query", limit: 100, what: "who to look up (query)"))
        case "calendar_read": return try await eventKit.calendarRead(args)
        case "calendar_add": return try await eventKit.calendarAdd(args)
        case "reminders_list": return try await eventKit.remindersList(args)
        case "reminders_add": return try await eventKit.remindersAdd(args)
        case "reminders_done": return try await eventKit.remindersDone(args)
        case "location_now":
            guard await foreground() else {
                throw ToolFailure("open Ira on the iPhone's screen first: iOS shares the location only with the app in use")
            }
            return try await LocationTool.now(args)
        case "call_place":
            return try await CallTool.place(args, foreground: await foreground(), open: opener)
        default:
            throw ToolFailure("this iPhone has no tool called \(name)")
        }
    }
}
