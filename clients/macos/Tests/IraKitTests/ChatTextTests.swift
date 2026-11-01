import Foundation
import Testing
@testable import IraKit

@Suite("Chat text")
struct ChatTextTests {
    func runs(_ text: AttributedString) -> [(String, AttributedString.Runs.Run)] {
        text.runs.map { (String(text[$0.range].characters), $0) }
    }

    @Test func boldItalicsAndCodeShowAsSuch() {
        let shown = ChatText.attributed(#"Your tab **"Booking - Sunrise Dental Clinic"** is open; run `make test` *now*."#)
        #expect(String(shown.characters) == #"Your tab "Booking - Sunrise Dental Clinic" is open; run make test now."#)
        let parts = runs(shown)
        #expect(parts.contains { $0.0 == #""Booking - Sunrise Dental Clinic""# && $0.1.inlinePresentationIntent == .stronglyEmphasized })
        #expect(parts.contains { $0.0 == "make test" && $0.1.inlinePresentationIntent == .code })
        #expect(parts.contains { $0.0 == "now" && $0.1.inlinePresentationIntent == .emphasized })
    }

    @Test func linksAreWordsNeverSomethingToClick() {
        let shown = ChatText.attributed("See [the clinic's page](https://example.com/pay?x=1) and ![a picture](https://example.com/a.png).")
        #expect(shown.runs.allSatisfy { $0.link == nil && $0.imageURL == nil })
        #expect(String(shown.characters).contains("the clinic's page"))
    }

    @Test func listsAndLineBreaksStay() {
        let shown = String(ChatText.attributed("Today:\n- 10:00 cleaning\n* 12:00 lunch\n  + 3:00 call").characters)
        #expect(shown == "Today:\n• 10:00 cleaning\n• 12:00 lunch\n  • 3:00 call")
        // Not a list: a dash inside a line, or a bold word at the start.
        #expect(String(ChatText.attributed("10 - 2 = 8\n**Bold** start").characters) == "10 - 2 = 8\nBold start")
    }

    @Test func plainTextIsUntouched() {
        let text = "Theek hai! 3 * 4 = 12, and that is all."
        #expect(String(ChatText.attributed(text).characters) == text)
    }
}
