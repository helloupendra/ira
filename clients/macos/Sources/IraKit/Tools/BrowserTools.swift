import AppKit
import Foundation

/// The browser skill: which tabs are open in Chrome, Safari, Arc, Edge and Brave,
/// and bringing one to the front so `screen_read` can read it.
///
/// Through Apple Events (macOS asks once per browser: "Ira wants to control
/// Google Chrome"). Ira reads only each tab's title and address (without the
/// part after `?` or `#`, which can hold private codes), never a page's
/// contents, form fields or passwords. To answer "how far is that upload?",
/// Ira brings the tab to the front (`browser_show_tab`, Tier 1) and reads the
/// screen (`screen_read`), as a person would look.
///
/// Only browsers that are already running are asked; none is ever started.
/// Each script is fixed: the browser's name comes from the list below, never
/// from the model, and the tab to show is passed as numbers in `argv`.
public enum BrowserTools {
    public struct Browser: Equatable, Sendable {
        public let key: String
        public let name: String
        public let bundleID: String
        let family: Family
    }

    enum Family: Sendable { case chromium, safari, arc }

    public static let browsers: [Browser] = [
        Browser(key: "chrome", name: "Google Chrome", bundleID: "com.google.Chrome", family: .chromium),
        Browser(key: "safari", name: "Safari", bundleID: "com.apple.Safari", family: .safari),
        Browser(key: "arc", name: "Arc", bundleID: "company.thebrowser.Browser", family: .arc),
        Browser(key: "edge", name: "Microsoft Edge", bundleID: "com.microsoft.edgemac", family: .chromium),
        Browser(key: "brave", name: "Brave Browser", bundleID: "com.brave.Browser", family: .chromium),
    ]

    public struct Tab: Equatable, Sendable {
        public let browser: String
        public let window: Int
        public let index: Int
        public let title: String
        public let url: String
        public let active: Bool

        public var id: String { "\(browser):\(window):\(index)" }
    }

    // MARK: The scripts

    /// The script that lists one browser's tabs: window, tab, title, address, active.
    static func listScript(_ browser: Browser) -> String {
        let row: String
        switch browser.family {
        case .chromium:
            row = """
                    set activeIndex to active tab index of w
                    set ti to 0
                    repeat with t in tabs of w
                        set ti to ti + 1
                        set out to out & wi & US & ti & US & (title of t) & US & (URL of t) & US & (ti = activeIndex) & RS
                    end repeat
            """
        case .safari:
            row = """
                    set activeIndex to index of current tab of w
                    set ti to 0
                    repeat with t in tabs of w
                        set ti to ti + 1
                        set out to out & wi & US & ti & US & (name of t) & US & (URL of t) & US & (ti = activeIndex) & RS
                    end repeat
            """
        case .arc:
            row = """
                    set activeID to ""
                    try
                        set activeID to id of active tab of w
                    end try
                    set ti to 0
                    repeat with t in tabs of w
                        set ti to ti + 1
                        set out to out & wi & US & ti & US & (title of t) & US & (URL of t) & US & ((id of t) = activeID) & RS
                    end repeat
            """
        }
        return """
            on run argv
                set US to character id 31
                set RS to character id 30
                set out to ""
                tell application "\(browser.name)"
                    set wi to 0
                    repeat with w in windows
                        set wi to wi + 1
                        try
            \(row)
                        end try
                    end repeat
                end tell
                return out
            end run
            """
    }

    /// The script that brings tab `item 2` of window `item 1` to the front.
    static func showScript(_ browser: Browser) -> String {
        let select: String
        switch browser.family {
        case .chromium:
            select = "set active tab index of w to ti"
        case .safari:
            select = "set current tab of w to tab ti of w"
        case .arc:
            select = "tell tab ti of w to select"
        }
        return """
            on run argv
                set wi to (item 1 of argv) as integer
                set ti to (item 2 of argv) as integer
                tell application "\(browser.name)"
                    set w to window wi
                    \(select)
                    set index of w to 1
                    activate
                end tell
                return "shown"
            end run
            """
    }

    // MARK: Reading the tabs

    /// An address without its query and fragment.
    public static func clean(_ url: String) -> String {
        guard let cut = url.firstIndex(where: { $0 == "?" || $0 == "#" }) else { return url }
        return String(url[..<cut])
    }

    static func parse(_ output: String, browser: Browser) -> [Tab] {
        AppleScriptTools.records(output).compactMap { fields in
            guard fields.count >= 5, let window = Int(fields[0]), let index = Int(fields[1]) else { return nil }
            return Tab(
                browser: browser.key, window: window, index: index, title: String(fields[2].prefix(300)),
                url: clean(fields[3]), active: fields[4] == "true")
        }
    }

    static func running(_ wanted: String?) async throws -> [Browser] {
        let candidates: [Browser]
        if let wanted {
            let key = wanted.lowercased()
            let matches = browsers.filter { $0.key == key || $0.name.lowercased().contains(key) }
            guard !matches.isEmpty else {
                throw ToolFailure("I can read Chrome, Safari, Arc, Edge and Brave, not \(wanted)")
            }
            candidates = matches
        } else {
            candidates = browsers
        }
        return await MainActor.run {
            candidates.filter { !NSRunningApplication.runningApplications(withBundleIdentifier: $0.bundleID).isEmpty }
        }
    }

    static func tabs(of browser: Browser) async throws -> [Tab] {
        parse(try await AppleScriptTools.run(listScript(browser), args: [], app: browser.name, timeout: 15), browser: browser)
    }

    /// The tab that best matches the words: every word in its title or address,
    /// the active tab of the front window first.
    public static func best(_ tabs: [Tab], matching query: String) -> Tab? {
        let words = query.lowercased().split(whereSeparator: \.isWhitespace).map(String.init)
        guard !words.isEmpty else { return nil }
        let matches = tabs.filter { tab in
            let haystack = (tab.title + " " + tab.url).lowercased()
            return words.allSatisfy(haystack.contains)
        }
        return matches.sorted { a, b in
            if a.active != b.active { return a.active }
            if a.window != b.window { return a.window < b.window }
            return a.index < b.index
        }.first
    }

    // MARK: The tools

    public static func listTabs(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["browser"])
        let open = try await running(try args.text("browser", limit: 40))
        guard !open.isEmpty else {
            throw ToolFailure("no browser is open. I can read Chrome, Safari, Arc, Edge and Brave while they are open")
        }
        var all: [Tab] = []
        var problems: [String] = []
        for browser in open {
            do {
                all += try await tabs(of: browser)
            } catch let failure as ToolFailure {
                problems.append(failure.message)
            }
        }
        if all.isEmpty, let problem = problems.first { throw ToolFailure(problem) }
        let shown = all.prefix(100)
        let items: [JSONValue] = shown.map { tab in
            [
                "id": .string(tab.id), "browser": .string(tab.browser), "window": .number(Double(tab.window)),
                "title": .string(tab.title), "url": .string(tab.url), "active": .bool(tab.active),
            ]
        }
        var lines: [String] = []
        for browser in open {
            let mine = shown.filter { $0.browser == browser.key }
            guard !mine.isEmpty else { continue }
            let titles = mine.prefix(10).map { $0.title.isEmpty ? "untitled" : $0.title }.joined(separator: "; ")
            let more = mine.count > 10 ? " and \(mine.count - 10) more" : ""
            var line = "\(browser.name): \(mine.count) tab\(mine.count == 1 ? "" : "s"): \(titles)\(more)."
            if let front = mine.first(where: { $0.window == 1 && $0.active }) {
                line += " In front: \(front.title.isEmpty ? "untitled" : front.title)."
            }
            lines.append(line)
        }
        return ["tabs": .array(items), "count": .number(Double(shown.count)), "summary": .string(lines.joined(separator: " "))]
    }

    public static func showTab(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["id", "match", "browser"])
        let id = try args.text("id", limit: 60)
        let match = try args.text("match", limit: 200)
        guard id != nil || match != nil else { throw ToolFailure("say which tab: words from its title or address, or its id") }
        var target: (Browser, Tab)?
        if let id {
            let parts = id.split(separator: ":").map(String.init)
            guard parts.count == 3, let browser = browsers.first(where: { $0.key == parts[0] }),
                let window = Int(parts[1]), let index = Int(parts[2])
            else { throw ToolFailure("that is not a tab id from browser_tabs") }
            let open = try await running(browser.key)
            guard !open.isEmpty else { throw ToolFailure("\(browser.name) is not open") }
            let list = try await tabs(of: browser)
            guard let tab = list.first(where: { $0.window == window && $0.index == index }) else {
                throw ToolFailure("that tab is no longer open")
            }
            target = (browser, tab)
        } else if let match {
            for browser in try await running(try args.text("browser", limit: 40)) {
                if let tab = best(try await tabs(of: browser), matching: match) {
                    target = (browser, tab)
                    break
                }
            }
            guard target != nil else { throw ToolFailure("no open tab matches \(match)") }
        }
        guard let (browser, tab) = target else { throw ToolFailure("no open tab matches that") }
        _ = try await AppleScriptTools.run(showScript(browser), args: [String(tab.window), String(tab.index)], app: browser.name, timeout: 10)
        try? await Task.sleep(nanoseconds: 700_000_000)  // let it draw before anyone reads the screen
        return [
            "id": .string(tab.id), "title": .string(tab.title), "url": .string(tab.url),
            "summary": .string("Brought “\(tab.title.isEmpty ? "the tab" : tab.title)” to the front in \(browser.name). Read the screen to see what it shows."),
        ]
    }
}
