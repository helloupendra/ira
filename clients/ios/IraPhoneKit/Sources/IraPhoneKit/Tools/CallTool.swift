import Foundation

/// `call_place` (Tier 2): Ira reads the number back and waits for the person's
/// yes; then the app opens a `tel:` link, and iOS shows its own "Call ...?"
/// prompt, which the person taps. iOS lets no app start a call by itself, and
/// only an app on screen may open the prompt.
public enum CallTool {
    /// The number to dial: digits and a leading +. Spaces, dashes, dots and
    /// brackets are dropped; anything else (`*`, `#`, letters) is refused, so no
    /// service code (`*21*...#`, call forwarding) can be dialled.
    public static func dialable(_ raw: String) throws -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        var out = ""
        for (index, char) in trimmed.enumerated() {
            if char.isASCII, char.isNumber {
                out.append(char)
            } else if char == "+" && index == 0 {
                out.append(char)
            } else if " -.()\u{00A0}".contains(char) {
                continue
            } else {
                throw ToolFailure("a number to call may hold only digits, spaces and a leading +")
            }
        }
        let digits = out.filter(\.isNumber).count
        guard (3...15).contains(digits) else {
            throw ToolFailure("that is not a phone number: give 3 to 15 digits")
        }
        return out
    }

    public static func telURL(_ number: String) -> URL? {
        URL(string: "tel:\(number)")
    }

    /// Open the iPhone's Call prompt for the number.
    public static func place(
        _ raw: JSONValue, foreground: Bool, open: @Sendable (URL) async -> Bool
    ) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["number", "name"])
        let number = try dialable(try args.required("number", limit: 40, what: "the number to call"))
        let name = try args.text("name", limit: 80)
        guard foreground else {
            throw ToolFailure("open Ira on the iPhone's screen first: iOS shows the Call prompt only for the app in front")
        }
        guard let url = telURL(number), await open(url) else {
            throw ToolFailure("this iPhone cannot make calls (an iPad or a simulator?)")
        }
        let who = name.map { "\($0), \(number)" } ?? number
        return [
            "number": .string(number),
            "summary": .string("The iPhone is asking to call \(who). The person taps Call to start it."),
        ]
    }
}
