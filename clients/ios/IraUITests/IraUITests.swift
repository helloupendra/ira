import XCTest

/// The app on an iOS simulator. The first test needs nothing else. The second
/// runs when CI (scripts/ci.sh) has started a local Ira with the demo model and
/// fake speech, and passes a pairing link in IRA_UITEST_LINK: it pairs, asks,
/// and lets Ira use a tool on this iPhone (the simulator's sample contacts).
final class IraUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor
    func testFirstRunShowsTheChecklistAndExplainsABadCode() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-setupDone", "NO"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Get Ira ready"].waitForExistence(timeout: 10))
        for title in ["Pair with your Ira", "Microphone", "Speech recognition", "Contacts", "Calendar", "Reminders", "Location", "Calls"] {
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch.exists, title)
        }
        XCTAssertFalse(app.buttons["start"].isEnabled)

        let pair = app.buttons["pair-action"]
        if pair.exists {
            pair.tap()
            let entry = app.textViews["pair-entry"].exists ? app.textViews["pair-entry"] : app.textFields["pair-entry"]
            XCTAssertTrue(entry.waitForExistence(timeout: 5))
            entry.tap()
            entry.typeText("hello")
            app.buttons["pair-button"].tap()
            XCTAssertTrue(app.staticTexts["pair-problem"].waitForExistence(timeout: 5))
            XCTAssertTrue(app.staticTexts["pair-problem"].label.contains("pairing link"))
        }
    }

    @MainActor
    func testPairAskAndUseAToolOnThisIPhone() throws {
        let link = ProcessInfo.processInfo.environment["IRA_UITEST_LINK"] ?? ""
        try XCTSkipIf(link.isEmpty, "no local Ira to pair with (CI starts one)")
        let app = XCUIApplication()
        addUIInterruptionMonitor(withDescription: "iOS asks") { alert in
            for title in ["Allow Full Access", "Allow", "OK", "Continue"] where alert.buttons[title].exists {
                alert.buttons[title].tap()
                return true
            }
            return false
        }
        app.launch()

        // Pair with the link, as if pasted.
        XCTAssertTrue(app.buttons["pair-action"].waitForExistence(timeout: 10))
        app.buttons["pair-action"].tap()
        let entry = app.textViews["pair-entry"].exists ? app.textViews["pair-entry"] : app.textFields["pair-entry"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        entry.tap()
        entry.typeText(link)
        app.buttons["pair-button"].tap()
        XCTAssertTrue(app.navigationBars["Get Ira ready"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.buttons["pair-action"].waitForExistence(timeout: 2), "still not paired")

        // The microphone (CI grants it to the simulator beforehand), then start.
        if app.buttons["microphone-action"].exists {
            app.buttons["microphone-action"].tap()
            app.tap()  // lets the interruption monitor answer iOS's prompt
        }
        let start = app.buttons["start"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        let enabled = NSPredicate(format: "isEnabled == true")
        expectation(for: enabled, evaluatedWith: start)
        waitForExpectations(timeout: 10)
        start.tap()

        // Typing: the demo model answers over /v1/ask/stream.
        let field = app.textFields["ask-field"].exists ? app.textFields["ask-field"] : app.textViews["ask-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("hello Ira")
        app.buttons["send"].tap()
        XCTAssertTrue(app.staticTexts["answer"].waitForExistence(timeout: 20))

        // A tool on this iPhone: Ira calls contacts_lookup over the device WebSocket,
        // and the simulator's sample contacts answer.
        field.tap()
        field.typeText("contacts lookup query=Kate")
        app.buttons["send"].tap()
        app.tap()
        let kate = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Kate Bell")).firstMatch
        XCTAssertTrue(kate.waitForExistence(timeout: 30), "Ira did not read the iPhone's contacts")
    }
}
