import Foundation
import Testing
@testable import IraKit

@Suite("The Drop list")
struct DropListTests {
    static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Kolkata")!
        calendar.locale = Locale(identifier: "en_IN")
        return calendar
    }

    @Test func newestFirstUnderTodayYesterdayAndOlderDates() {
        let now = Date(timeIntervalSince1970: 1_793_440_000)  // 31 Oct 2026, afternoon in India
        let hour: TimeInterval = 3600
        let items = [
            DropItem(id: 3, kind: "text", text: "call the CA", createdAt: now - hour),
            DropItem(id: 9, kind: "link", text: "https://example.com", createdAt: now - 60),
            DropItem(id: 2, kind: "file", name: "plan.pdf", createdAt: now - 26 * hour),
            DropItem(id: 1, kind: "text", text: "old", createdAt: now - 4 * 24 * hour),
            DropItem(id: 0, kind: "text", text: "no date"),
        ]
        let sections = DropList.sections(items, now: now, calendar: DropListTests.calendar)
        #expect(sections.map(\.title).prefix(2) == ["Today", "Yesterday"])
        #expect(sections.map { $0.items.map(\.id) } == [[9, 3], [2], [1], [0]])
        #expect(sections[2].title.contains("27") && sections[3].title == "Earlier")
    }

    @Test func eachKindHasItsIconTitleAndDetail() throws {
        let file = DropItem(id: 4, kind: "file", text: "v2", name: "a/plan.pdf", mime: "application/pdf", size: 3000, fromLabel: "Pixel 7",
                            createdAt: Date(timeIntervalSince1970: 1_793_440_000))
        #expect(DropList.symbol(file) == "doc.richtext")
        #expect(DropList.title(file) == "plan.pdf")
        #expect(DropList.detail(file, calendar: DropListTests.calendar).hasPrefix("From Pixel 7 · "))
        #expect(DropList.detail(file, calendar: DropListTests.calendar).hasSuffix(" · 2.9 KB · v2"))
        #expect(DropList.symbol(DropItem(id: 5, kind: "file", name: "photo.JPG")) == "photo")
        #expect(DropList.symbol(DropItem(id: 6, kind: "file", name: "notes.zqx")) == "doc")
        #expect(DropList.symbol(DropItem(id: 7, kind: "link", text: "https://example.com")) == "link")
        let text = DropItem(id: 8, kind: "text", text: "call\n the   CA")
        #expect(DropList.symbol(text) == "text.alignleft" && DropList.title(text) == "call the CA")
        #expect(DropList.detail(text) == "From a device")
    }

    @Test func theItemCarriesWhenItWasSent() throws {
        let item = try #require(DropItem(["id": 1, "kind": "text", "text": "hi", "created_at": "2026-10-31T08:00:00Z"]))
        #expect(item.createdAt == Date(timeIntervalSince1970: 1_793_433_600))
    }
}
