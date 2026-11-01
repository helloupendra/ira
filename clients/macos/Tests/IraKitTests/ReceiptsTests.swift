import Foundation
import Testing
@testable import IraKit

@Suite("Receipts under an answer")
struct ReceiptsTests {
    @Test func eachToolRunsUntilTheTurnsNextEvent() {
        let start = Date(timeIntervalSince1970: 1_000)
        var receipts = Receipts()
        receipts.began("files_find", turn: 3, at: start)
        receipts.began("file_read", turn: 3, at: start + 0.42)
        receipts.ended(turn: 3, at: start + 1.6)
        receipts.began("screen_read", turn: 4, at: start + 2)
        #expect(receipts.take(turn: 3, at: start + 5) == ["files find · 0.4 s", "file read · 1.2 s"])
        #expect(receipts.take(turn: 3).isEmpty)  // once
        #expect(receipts.take(turn: 4, at: start + 14.6) == ["screen read · 13 s"])
        var none = Receipts()
        #expect(none.take(turn: 9).isEmpty)
    }

    @Test func toolsDoneSoFarShowOneByOne() {
        let start = Date(timeIntervalSince1970: 1_000)
        var receipts = Receipts()
        receipts.began("ai_sessions", turn: 5, at: start)
        #expect(receipts.finished(turn: 5).isEmpty)  // still running
        receipts.began("web_search", turn: 5, at: start + 0.8)
        #expect(receipts.finished(turn: 5) == ["ai sessions · 0.8 s"])
        receipts.ended(turn: 5, at: start + 2)
        #expect(receipts.finished(turn: 5) == ["ai sessions · 0.8 s", "web search · 1.2 s"])
        #expect(receipts.take(turn: 5, at: start + 3).count == 2)  // still there for the answer
    }
}
