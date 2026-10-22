import Foundation

/// Mail, Notes and Messages, through AppleScript (`osascript`).
///
/// What the model wrote never becomes script text: each script is fixed, and
/// the arguments reach it as `argv`, so a subject like `" & do shell script`
/// is only ever a string. macOS asks the person once per app ("Ira wants to
/// control Mail"); the answer lives in Privacy & Security → Automation.
///
/// * `mail_search`, `mail_read` (Tier 0), `mail_draft` (Tier 2: a draft opens in
///   Mail for the person to check; Ira never presses Send);
/// * `notes_search`, `notes_read` (Tier 0), `notes_add` (Tier 1);
/// * `messages_send` (Tier 2): an iMessage to a number or an email address.
public enum AppleScriptTools {
    public static let unit = "\u{1F}"
    public static let record = "\u{1E}"

    /// Split a script's output into records of fields.
    public static func records(_ output: String) -> [[String]] {
        output.components(separatedBy: record)
            .map { $0.trimmingCharacters(in: .newlines) }
            .filter { !$0.isEmpty }
            .map { $0.components(separatedBy: unit) }
    }

    /// Why a script failed, in words, with what to do about a permission.
    public static func failure(_ app: String, _ stderr: String) -> ToolFailure {
        if stderr.contains("-1743") || stderr.localizedCaseInsensitiveContains("not authorized") {
            return ToolFailure(
                "Ira may not use \(app) yet. Allow Ira for \(app) in System Settings → Privacy & Security → Automation, then ask again")
        }
        if stderr.contains("-1728") || stderr.contains("-1719") {
            return ToolFailure("\(app) has nothing that matches")
        }
        if stderr.contains("-600") || stderr.contains("-1712") {
            return ToolFailure("\(app) did not answer in time")
        }
        let line = stderr.split(separator: "\n").last.map(String.init) ?? "it failed"
        return ToolFailure("\(app) said: \(line.prefix(200))")
    }

    /// Run a fixed script with `argv`, at most `timeout` seconds.
    static func run(_ script: String, args: [String], app: String, timeout: Double = 20) async throws -> String {
        let result = try await Command.run(["/usr/bin/osascript", "-", ] + args, input: script, timeout: timeout)
        if result.timedOut { throw ToolFailure("\(app) did not answer in time") }
        guard result.status == 0 else { throw failure(app, result.stderr) }
        return result.stdout.trimmingCharacters(in: .newlines)
    }

    // MARK: Mail

    static let mailSearch = """
        on run argv
            set q to item 1 of argv
            set sinceDays to (item 2 of argv) as integer
            set US to character id 31
            set RS to character id 30
            set cutoff to (current date) - (sinceDays * days)
            set out to ""
            set n to 0
            tell application "Mail"
                set found to (messages of inbox whose date received > cutoff)
                repeat with m in found
                    set s to subject of m
                    set f to sender of m
                    if q is "" or s contains q or f contains q then
                        set mb to mailbox of m
                        set accountName to ""
                        try
                            set accountName to name of account of mb
                        end try
                        set out to out & (id of m) & US & (name of mb) & US & accountName & US & s & US & f & US & ((date received of m) as «class isot» as string) & US & (read status of m) & RS
                        set n to n + 1
                        if n > 199 then exit repeat
                    end if
                end repeat
            end tell
            return out
        end run
        """

    static let mailRead = """
        on run argv
            set accountName to item 1 of argv
            set mailboxName to item 2 of argv
            set messageId to (item 3 of argv) as integer
            set US to character id 31
            tell application "Mail"
                if accountName is "" then
                    set mb to mailbox mailboxName
                else
                    set mb to mailbox mailboxName of account accountName
                end if
                set m to first message of mb whose id is messageId
                set recipientsText to ""
                repeat with r in to recipients of m
                    set recipientsText to recipientsText & (address of r) & ", "
                end repeat
                return (subject of m) & US & (sender of m) & US & ((date received of m) as «class isot» as string) & US & recipientsText & US & (content of m)
            end tell
        end run
        """

    static let mailDraft = """
        on run argv
            set US to character id 31
            set AppleScript's text item delimiters to US
            set toList to text items of (item 1 of argv)
            set ccList to text items of (item 2 of argv)
            set AppleScript's text item delimiters to ""
            set s to item 3 of argv
            set b to item 4 of argv
            tell application "Mail"
                set m to make new outgoing message with properties {subject:s, content:b & return, visible:true}
                tell m
                    repeat with a in toList
                        if (a as string) is not "" then make new to recipient at end of to recipients with properties {address:(a as string)}
                    end repeat
                    repeat with a in ccList
                        if (a as string) is not "" then make new cc recipient at end of cc recipients with properties {address:(a as string)}
                    end repeat
                end tell
                try
                    save m
                end try
                activate
            end tell
            return "drafted"
        end run
        """

    /// A mail id as Ira passes it around: account, mailbox and message id.
    public static func mailID(account: String, mailbox: String, id: String) -> String {
        [account, mailbox, id].joined(separator: "/")
    }

    public static func parseMailID(_ text: String) -> (account: String, mailbox: String, id: String)? {
        let parts = text.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard parts.count >= 3, let id = parts.last, Int(id) != nil else { return nil }
        let account = parts[0]
        let mailbox = parts[1..<(parts.count - 1)].joined(separator: "/")
        return (account, mailbox, id)
    }

    public static func mailSearch(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["query", "days", "limit"])
        let query = try args.text("query", limit: 100) ?? ""
        let days = try args.number("days", 1...365) ?? 14
        let limit = try args.number("limit", 1...25) ?? 10
        let output = try await run(mailSearch, args: [query, String(days)], app: "Mail", timeout: 22)
        let rows = records(output).filter { $0.count >= 7 }
            .sorted { $0[5] > $1[5] }  // newest first (ISO dates sort as text)
            .prefix(limit)
        let messages: [JSONValue] = rows.map { row in
            [
                "id": .string(mailID(account: row[2], mailbox: row[1], id: row[0])),
                "subject": .string(row[3]),
                "from": .string(row[4]),
                "date": .string(row[5]),
                "read": .bool(row[6] == "true"),
            ]
        }
        let summary = messages.isEmpty
            ? "No emails in the inbox match\(query.isEmpty ? "" : " \(query)") in the last \(days) days."
            : "\(messages.count) email\(messages.count == 1 ? "" : "s"): " + rows.prefix(5).map { "\($0[3]) from \($0[4])" }.joined(separator: "; ") + "."
        return ["messages": .array(messages), "count": .number(Double(messages.count)), "summary": .string(summary)]
    }

    public static func mailRead(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "maxChars"])
        guard let id = parseMailID(try args.required("id", limit: 400, what: "which email (its id from mail_search)")) else {
            throw ToolFailure("that is not an email id from mail_search")
        }
        let maxChars = try args.number("maxChars", 200...Toolbox.maxText) ?? Toolbox.maxText
        let output = try await run(mailRead, args: [id.account, id.mailbox, id.id], app: "Mail")
        let fields = output.components(separatedBy: unit)
        guard fields.count >= 5 else { throw ToolFailure("Mail gave nothing back for that email") }
        let body = FileText.cut(fields[4...].joined(separator: unit), kind: "email", maxChars: maxChars)
        return [
            "subject": .string(fields[0]), "from": .string(fields[1]), "date": .string(fields[2]),
            "to": .string(fields[3].trimmingCharacters(in: CharacterSet(charactersIn: ", "))),
            "text": .string(body.text), "truncated": .bool(body.truncated),
            "summary": .string("The email “\(fields[0])” from \(fields[1])."),
        ]
    }

    static let email = try! NSRegularExpression(pattern: #"^[^@\s]+@[^@\s]+\.[^@\s]+$"#)

    public static func isEmail(_ text: String) -> Bool {
        email.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }

    public static func mailDraft(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["to", "cc", "subject", "body"])
        let to = try args.list("to")
        let cc = try args.list("cc")
        guard !to.isEmpty else { throw ToolFailure("say who the email is to: their email address") }
        for address in to + cc where !isEmail(address) {
            throw ToolFailure("\(address) is not an email address; look it up with contacts_lookup first")
        }
        let subject = try args.text("subject", limit: 300) ?? ""
        let body = try args.text("body", limit: 20_000) ?? ""
        _ = try await run(mailDraft, args: [to.joined(separator: unit), cc.joined(separator: unit), subject, body], app: "Mail")
        return [
            "summary": .string("Drafted an email to \(to.joined(separator: ", ")): “\(subject)”. It is open in Mail for you to check and send."),
        ]
    }

    // MARK: Notes

    static let notesSearch = """
        on run argv
            set q to item 1 of argv
            set US to character id 31
            set RS to character id 30
            set out to ""
            set n to 0
            tell application "Notes"
                if q is "" then
                    set found to notes
                else
                    set found to (notes whose name contains q or plaintext contains q)
                end if
                repeat with x in found
                    set folderName to ""
                    try
                        set folderName to name of container of x
                    end try
                    set out to out & (id of x) & US & (name of x) & US & folderName & US & ((modification date of x) as «class isot» as string) & RS
                    set n to n + 1
                    if n > 99 then exit repeat
                end repeat
            end tell
            return out
        end run
        """

    static let notesRead = """
        on run argv
            set US to character id 31
            tell application "Notes"
                set x to note id (item 1 of argv)
                return (name of x) & US & ((modification date of x) as «class isot» as string) & US & (plaintext of x)
            end tell
        end run
        """

    static let notesAdd = """
        on run argv
            set folderName to item 1 of argv
            set b to item 2 of argv
            tell application "Notes"
                if folderName is "" then
                    set x to make new note with properties {body:b}
                else
                    set x to make new note at folder folderName with properties {body:b}
                end if
                return id of x
            end tell
        end run
        """

    /// A note's body as Notes stores it (HTML): the title in bold, then the lines.
    public static func noteHTML(title: String, body: String) -> String {
        func escape(_ text: String) -> String {
            text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
                .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
        }
        let lines = body.components(separatedBy: .newlines).map { "<div>\($0.isEmpty ? "<br>" : escape($0))</div>" }
        return "<div><b>\(escape(title))</b></div>" + lines.joined()
    }

    public static func notesSearch(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["query", "limit"])
        let query = try args.text("query", limit: 100) ?? ""
        let limit = try args.number("limit", 1...25) ?? 10
        let rows = records(try await run(notesSearch, args: [query], app: "Notes", timeout: 22)).filter { $0.count >= 4 }
            .sorted { $0[3] > $1[3] }.prefix(limit)
        let notes: [JSONValue] = rows.map { ["id": .string($0[0]), "title": .string($0[1]), "folder": .string($0[2]), "modified": .string($0[3])] }
        let summary = notes.isEmpty
            ? "No notes match\(query.isEmpty ? "" : " \(query)")."
            : "\(notes.count) note\(notes.count == 1 ? "" : "s"): " + rows.prefix(5).map { $0[1] }.joined(separator: "; ") + "."
        return ["notes": .array(notes), "count": .number(Double(notes.count)), "summary": .string(summary)]
    }

    public static func notesRead(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "maxChars"])
        let id = try args.required("id", limit: 300, what: "which note (its id from notes_search)")
        guard id.hasPrefix("x-coredata://") else { throw ToolFailure("that is not a note id from notes_search") }
        let maxChars = try args.number("maxChars", 200...Toolbox.maxText) ?? Toolbox.maxText
        let fields = try await run(notesRead, args: [id], app: "Notes").components(separatedBy: unit)
        guard fields.count >= 3 else { throw ToolFailure("Notes gave nothing back for that note") }
        let text = FileText.cut(fields[2...].joined(separator: unit), kind: "note", maxChars: maxChars)
        return [
            "title": .string(fields[0]), "modified": .string(fields[1]), "text": .string(text.text),
            "truncated": .bool(text.truncated), "summary": .string("The note “\(fields[0])”."),
        ]
    }

    public static func notesAdd(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["title", "body", "folder"])
        let title = try args.required("title", limit: 200, what: "the note's title")
        let body = try args.text("body", limit: 20_000) ?? ""
        let folder = try args.text("folder", limit: 100) ?? ""
        let id = try await run(notesAdd, args: [folder, noteHTML(title: title, body: body)], app: "Notes")
        return ["id": .string(id), "summary": .string("Added the note “\(title)”\(folder.isEmpty ? "" : " to \(folder)").")]
    }

    // MARK: Messages

    static let messagesSend = """
        on run argv
            set handleText to item 1 of argv
            set messageText to item 2 of argv
            tell application "Messages"
                set svc to 1st account whose service type = iMessage
                set p to participant handleText of svc
                send messageText to p
            end tell
            return "sent"
        end run
        """

    /// A number or an email address Messages can send to, cleaned; nil otherwise.
    public static func messageHandle(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if isEmail(trimmed) { return trimmed }
        let allowed = CharacterSet(charactersIn: "+0123456789 -().")
        guard trimmed.unicodeScalars.allSatisfy(allowed.contains) else { return nil }
        let digits = trimmed.filter(\.isNumber)
        guard (6...15).contains(digits.count) else { return nil }
        return (trimmed.hasPrefix("+") ? "+" : "") + digits
    }

    public static func messagesSend(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["to", "name", "text"])
        let to = try args.required("to", limit: 200, what: "who to send it to: their number or email")
        guard let handle = messageHandle(to) else {
            throw ToolFailure("\(to) is not a phone number or an email address; look it up with contacts_lookup first")
        }
        let text = try args.required("text", limit: 4000, what: "what to say (text)")
        let name = try args.text("name", limit: 100)
        _ = try await run(messagesSend, args: [handle, text], app: "Messages")
        return ["summary": .string("Sent your message to \(name.map { "\($0) (\(handle))" } ?? handle).")]
    }
}
