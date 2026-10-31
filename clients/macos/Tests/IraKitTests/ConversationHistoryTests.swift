import Foundation
import Testing
@testable import IraKit

@Suite("Today's conversations")
struct ConversationHistoryTests {
    @Test func rowsParseAndTodayComesLatestFirst() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Kolkata")!
        let now = Date(timeIntervalSince1970: 1_793_440_000)  // 31 Oct 2026, 13:16 in India
        let start = calendar.startOfDay(for: now).timeIntervalSince1970
        let rows: JSONValue = [
            ["id": "a", "channel": "api", "started_at": .number(start + 600), "last_at": .number(start + 900), "turns": 2, "preview": "vo PDF kahan hai"],
            ["id": "b", "channel": "web", "started_at": .number(start - 7200), "last_at": .number(start - 60), "turns": 1],
            ["id": "c", "channel": "api", "started_at": .number(start + 1000), "last_at": .number(start + 3000), "turns": 1, "preview": "  "],
            ["channel": "api"],
        ]
        let parsed = (rows.arrayValue ?? []).compactMap(ConversationSummary.init)
        #expect(parsed.map(\.id) == ["a", "b", "c"])
        let today = ConversationHistory.today(parsed, now: now, calendar: calendar)
        #expect(today.map(\.id) == ["c", "a"])
        #expect(today[1].title == "vo PDF kahan hai")
        #expect(today[0].preview == nil && today[0].title.hasPrefix("Conversation at "))
    }

    @Test func aTranscriptShowsWordsAnswersAndActionsNeverTools() {
        let messages: JSONValue = [
            ["id": 1, "role": "user", "content": "send the invoice to Sunrise", "tool_calls": []],
            ["id": 2, "role": "assistant", "content": "", "tool_calls": [["id": "c1", "name": "send_invoice", "arguments": "{}"]]],
            ["id": 3, "role": "tool", "content": "{\"status\": \"pending_confirmation\"}", "tool_call_id": "c1", "name": "send_invoice",
             "action": ["id": "act_1", "summary": "Send invoice INV-7 to Sunrise Dental Clinic", "status": "executed"]],
            ["id": 4, "role": "assistant", "content": "Sent.", "tool_calls": []],
        ]
        #expect(ConversationHistory.lines(messages) == [
            ConversationLine(.person, "send the invoice to Sunrise"),
            ConversationLine(.note, "Done: Send invoice INV-7 to Sunrise Dental Clinic"),
            ConversationLine(.ira, "Sent."),
        ])
    }
}
