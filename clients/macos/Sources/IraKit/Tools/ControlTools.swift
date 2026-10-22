import AppKit
import ApplicationServices
import Carbon.HIToolbox
import Foundation

/// The five control tools (`mac_type`, `mac_keys`, `mac_click`, `mac_scroll`,
/// `mac_menu`): find the app, bring it to the front, check it is one Ira may
/// work in, act, and say what was done. See `MacControl` for the rules.
struct ControlTools: Sendable {
    let frontApp: Toolbox.FrontApp
    let log: IraLog

    struct Target: @unchecked Sendable {
        let pid: pid_t
        let name: String
        let app: AXNode
    }

    nonisolated(unsafe) private static var askedForTrust = false

    // MARK: The app to act in

    func target(_ step: MacControl.Step) async throws -> Target {
        guard MacControl.trusted else {
            if !ControlTools.askedForTrust && MacControl.mayPrompt {
                ControlTools.askedForTrust = true
                await MainActor.run { _ = MacControl.requestTrust() }
            }
            throw ToolFailure(MacControl.notTrusted)
        }
        let running: NSRunningApplication?
        if let wanted = step.app {
            running = await MainActor.run { ControlTools.runningApp(named: wanted) }
            guard running != nil else { throw ToolFailure("\(wanted) is not open. Open it first with app_open") }
        } else {
            guard let front = await frontApp() else { throw ToolFailure("no app is in front. Say which app") }
            running = await MainActor.run { NSRunningApplication(processIdentifier: front.pid) }
        }
        guard let running, !running.isTerminated else { throw ToolFailure("that app is no longer open") }
        let pid = running.processIdentifier
        let name = running.localizedName ?? "the app"
        let bundleID = running.bundleIdentifier
        // Refuse before bringing anything forward.
        if let refusal = MacControl.refusal(bundleID: bundleID, app: name, window: nil),
            bundleID != "com.apple.systempreferences"
        {
            throw ToolFailure(refusal)
        }
        let app = AXNode(AXUIElementCreateApplication(pid))
        AXUIElementSetMessagingTimeout(app.element, 1.5)
        if await MainActor.run(body: { NSWorkspace.shared.frontmostApplication?.processIdentifier }) != pid {
            _ = await MainActor.run { running.activate(options: []) }
            app.set(kAXFrontmostAttribute, kCFBooleanTrue)
            for _ in 0..<15 {
                if await MainActor.run(body: { NSWorkspace.shared.frontmostApplication?.processIdentifier }) == pid { break }
                try await Task.sleep(nanoseconds: 100_000_000)
            }
        }
        let window = app.focusedWindow?.string(kAXTitleAttribute)
        if let refusal = MacControl.refusal(bundleID: bundleID, app: name, window: window) { throw ToolFailure(refusal) }
        return Target(pid: pid, name: name, app: app)
    }

    /// A running app with a window, by the name the person uses.
    @MainActor
    static func runningApp(named wanted: String) -> NSRunningApplication? {
        let apps = NSWorkspace.shared.runningApplications.filter { $0.activationPolicy == .regular }
        let names = apps.compactMap(\.localizedName)
        guard let best = AppTools.bestApp(wanted, among: names) else { return nil }
        return apps.first { $0.localizedName == best }
    }

    /// The app in front after a step: its name, and its bundle id, which an
    /// approval for trusted apps checks (`"app"` in every result).
    struct Front {
        let name: String
        let bundleID: String
    }

    func inFront() async -> Front {
        try? await Task.sleep(nanoseconds: 250_000_000)
        return await MainActor.run {
            let app = NSWorkspace.shared.frontmostApplication
            return Front(name: app?.localizedName ?? "no app", bundleID: app?.bundleIdentifier ?? "")
        }
    }

    /// Act with Ira's own window out of the keyboard's way.
    func acting<T>(_ body: () async throws -> T) async rethrows -> T {
        await MainActor.run { NotificationCenter.default.post(name: MacControl.acting, object: nil) }
        try? await Task.sleep(nanoseconds: 80_000_000)
        defer { Task { @MainActor in NotificationCenter.default.post(name: MacControl.acted, object: nil) } }
        return try await body()
    }

    func refuseSecureFocus(in target: Target) throws {
        if IsSecureEventInputEnabled() {
            throw ToolFailure("a password field is active on this Mac (secure typing is on), so I don't type or press keys now. Do this step yourself")
        }
        if let focused = AXNode(AXUIElementCreateSystemWide()).focused, focused.pid == target.pid,
            MacControl.isSecure(role: focused.role, subrole: focused.subrole)
        {
            throw ToolFailure("the cursor is in a password field in \(target.name): I never type passwords. Type it yourself")
        }
    }

    // MARK: mac_type

    func type(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["text", "app", "pressReturn", "task"])
        let text = try args.required("text", limit: 2000, what: "what to type (text)")
        let pressReturn = try args.bool("pressReturn") ?? false
        let target = try await target(try MacControl.step(args))
        try await Task.sleep(nanoseconds: 150_000_000)
        guard let focused = AXNode(AXUIElementCreateSystemWide()).focused, focused.pid == target.pid else {
            throw ToolFailure("nothing in \(target.name) is ready for typing. Put the cursor in the field first with mac_click")
        }
        try refuseSecureFocus(in: target)
        let field = MacControl.kind(focused.role)
        await acting {
            ControlTools.post(text: text)
            if pressReturn { ControlTools.post(MacControl.KeyPress(code: CGKeyCode(kVK_Return), flags: 0, spoken: "Return")) }
        }
        // A check that needs no screen text in the answer: does the field now hold it?
        let lastLine = text.split(separator: "\n").last.map(String.init) ?? text
        let landed = focused.string(kAXValueAttribute).map { $0.contains(lastLine) }
        let front = await inFront()
        log.info("mac_type \(text.count) chars into a \(field) in \(target.name)")
        var summary = "Typed \(text.count) character\(text.count == 1 ? "" : "s") into the \(field) in \(target.name)"
        summary += pressReturn ? ", then pressed Return." : "."
        if landed == false && !pressReturn { summary += " The field does not show them: look with screen_read." }
        summary += " \(front.name) is in front now."
        return [
            "typed": .number(Double(text.count)), "actedIn": .string(target.name), "field": .string(field),
            "pressedReturn": .bool(pressReturn), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string(summary),
        ]
    }

    // MARK: mac_keys

    func keys(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["keys", "app", "task"])
        let presses = try MacControl.parseKeys(try args.required("keys", limit: 200, what: "which keys, e.g. cmd+l or return"))
        let target = try await target(try MacControl.step(args))
        try refuseSecureFocus(in: target)
        await acting {
            for press in presses {
                ControlTools.post(press)
                usleep(60_000)
            }
        }
        let front = await inFront()
        let said = presses.map(\.spoken).joined(separator: ", then ")
        log.info("mac_keys \(presses.count) presses in \(target.name)")
        return [
            "pressed": .array(presses.map { .string($0.spoken) }), "actedIn": .string(target.name), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string("Pressed \(said) in \(target.name). \(front.name) is in front now."),
        ]
    }

    // MARK: mac_click

    func click(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["label", "role", "index", "app", "task"])
        let label = try args.required("label", limit: 200, what: "what to click: its label as shown")
        var role = try args.text("role")?.lowercased()
        if role == "any" { role = nil }
        if let role, MacControl.roles[role] == nil {
            throw ToolFailure("role must be one of: \((MacControl.roles.keys.sorted() + ["any"]).joined(separator: ", "))")
        }
        let index = try args.number("index", 1...20)
        let target = try await target(try MacControl.step(args))
        guard let window = target.app.focusedWindow else { throw ToolFailure("\(target.name) has no window open in front") }
        // Chrome and Electron apps show their pages to Accessibility only when asked.
        let asked = target.app.set("AXManualAccessibility", kCFBooleanTrue)
        var matches = MacControl.find(label, role: role, in: window)
        if matches.isEmpty && asked {
            try await Task.sleep(nanoseconds: 500_000_000)
            matches = MacControl.find(label, role: role, in: window)
        }
        if !matches.isEmpty {
            let match: MacControl.Match<AXNode>
            switch MacControl.choose(matches, index: index) {
            case .success(let chosen): match = chosen
            case .failure(let failure): throw failure
            }
            return try await press(match, in: target)
        }
        return try await clickWords(label, index: index, in: target)
    }

    private func press(_ match: MacControl.Match<AXNode>, in target: Target) async throws -> JSONValue {
        let node = match.node
        let kind = match.actionable ? MacControl.kind(node.role) : "words"
        guard node.enabled else { throw ToolFailure("the “\(match.label)” \(kind) in \(target.name) is greyed out now") }
        var did: String
        let done: Bool = await acting {
            if MacControl.textRoles.contains(node.role) {
                return node.set(kAXFocusedAttribute, kCFBooleanTrue)
            }
            if !match.actionable, let frame = node.frame {
                ControlTools.post(click: CGPoint(x: frame.midX, y: frame.midY))
                return true
            }
            if let action = MacControl.pressActions.first(where: node.actions.contains), node.perform(action) { return true }
            if ["AXRow", "AXCell", "AXOutlineRow"].contains(node.role), node.set(kAXSelectedAttribute, kCFBooleanTrue) { return true }
            // The control would not take the action: click where it is.
            if let frame = node.frame, frame.width > 0, frame.height > 0 {
                ControlTools.post(click: CGPoint(x: frame.midX, y: frame.midY))
                return true
            }
            return false
        }
        guard done else { throw ToolFailure("the “\(match.label)” \(kind) in \(target.name) did not respond") }
        did = MacControl.textRoles.contains(node.role)
            ? "Put the cursor in the “\(match.label)” \(kind) in \(target.name), ready for mac_type."
            : match.actionable
                ? "Clicked the “\(match.label)” \(kind) in \(target.name)."
                : "No control is called “\(match.label)”, so I clicked where those words are, in \(target.name)."
        let front = await inFront()
        log.info("mac_click a \(kind) in \(target.name)")
        return [
            "clicked": .string(match.label), "kind": .string(kind), "actedIn": .string(target.name), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string("\(did) \(front.name) is in front now. Look with screen_read before the next step."),
        ]
    }

    /// The last resort: no control has that name, so click where the words are written.
    private func clickWords(_ label: String, index: Int?, in target: Target) async throws -> JSONValue {
        let notFound = "No button, link or field called “\(label)” in \(target.name)'s front window"
        guard ScreenText.permitted, ScreenText.permittedAtLaunch else {
            throw ToolFailure(notFound + ". Look with screen_read, then use the exact label")
        }
        guard let window = ScreenText.frontWindow(of: target.pid) else { throw ToolFailure(notFound) }
        let points = try await withTimeout(8) { try await ScreenText.locate(label, in: window) }
        guard !points.isEmpty else { throw ToolFailure(notFound + ", and those words are not on it. Look with screen_read") }
        if points.count > 1 && index == nil {
            throw ToolFailure("“\(label)” is written \(points.count) times in \(target.name)'s window. Say which with index, 1 for the one nearest the top")
        }
        let at = (index ?? 1) - 1
        guard points.indices.contains(at) else { throw ToolFailure("index goes from 1 to \(points.count)") }
        await acting { ControlTools.post(click: points[at]) }
        let front = await inFront()
        log.info("mac_click words in \(target.name)")
        return [
            "clicked": .string(label), "kind": .string("words"), "actedIn": .string(target.name), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string("No control is called “\(label)”, so I clicked where those words are written in \(target.name)'s window. \(front.name) is in front now. Look with screen_read before the next step."),
        ]
    }

    // MARK: mac_scroll

    func scroll(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["direction", "amount", "app", "task"])
        let direction = try args.required("direction", limit: 10, what: "which way: up, down, left or right").lowercased()
        guard ["up", "down", "left", "right"].contains(direction) else { throw ToolFailure("direction must be up, down, left or right") }
        let amount = try args.number("amount", 1...30) ?? 5
        let target = try await target(try MacControl.step(args))
        guard let frame = target.app.focusedWindow?.frame else { throw ToolFailure("\(target.name) has no window open in front") }
        let middle = CGPoint(x: frame.midX, y: frame.midY)
        await acting {
            ControlTools.post(move: middle)
            for _ in 0..<amount {
                ControlTools.post(scroll: direction, lines: 3)
                usleep(25_000)
            }
        }
        let front = await inFront()
        log.info("mac_scroll \(direction) \(amount) in \(target.name)")
        return [
            "scrolled": .string(direction), "steps": .number(Double(amount)), "actedIn": .string(target.name), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string("Scrolled \(direction) \(amount) step\(amount == 1 ? "" : "s") in \(target.name)'s window. \(front.name) is in front now."),
        ]
    }

    // MARK: mac_menu

    /// Menus whose items name pages, people or windows: their items are not listed back.
    static let personalMenus: Set<String> = ["history", "bookmarks", "window", "favourites", "favorites", "go", "recent"]

    func menu(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["path", "app", "task"])
        let path = try MacControl.menuPath(try args.required("path", limit: 300, what: "which menu item, e.g. File > New Window"))
        let target = try await target(try MacControl.step(args))
        guard let bar = target.app.node(kAXMenuBarAttribute) else { throw ToolFailure("\(target.name) has no menu bar") }
        // The first item is the Apple menu: never used.
        var items = Array(bar.nodes.filter { $0.role == "AXMenuBarItem" }.dropFirst())
        var chosen: AXNode?
        var trail: [String] = []
        for (depth, wanted) in path.enumerated() {
            let titles = items.map { $0.string(kAXTitleAttribute) ?? "" }
            guard let at = MacControl.pick(wanted, among: titles) else {
                let shown = depth == 0 || !ControlTools.personalMenus.contains(MacControl.normal(trail.first ?? ""))
                    ? " It has: " + titles.filter { !$0.isEmpty }.prefix(25).map { "“\($0.prefix(40))”" }.joined(separator: ", ") + "."
                    : ""
                let place = trail.isEmpty ? "\(target.name)'s menu bar" : "\(target.name)'s \(trail.joined(separator: " → ")) menu"
                throw ToolFailure("there is no “\(wanted)” in \(place).\(shown)")
            }
            let item = items[at]
            trail.append(titles[at])
            chosen = item
            if depth < path.count - 1 {
                guard let submenu = item.nodes.first(where: { $0.role == "AXMenu" }) else {
                    throw ToolFailure("“\(titles[at])” in \(target.name) has no menu under it")
                }
                items = submenu.nodes.filter { $0.role == "AXMenuItem" && ($0.string(kAXTitleAttribute) ?? "") != "" }
            }
        }
        guard let item = chosen else { throw ToolFailure("say which menu item") }
        let said = trail.joined(separator: " → ")
        guard item.enabled else { throw ToolFailure("\(said) is greyed out in \(target.name) now") }
        let done = await acting { item.perform("AXPress") || item.perform("AXPick") }
        guard done else { throw ToolFailure("\(said) in \(target.name) did not respond") }
        let front = await inFront()
        log.info("mac_menu \(path.count) steps in \(target.name)")
        return [
            "chose": .string(said), "actedIn": .string(target.name), "app": .string(front.bundleID), "appName": .string(front.name),
            "summary": .string("Chose \(said) in \(target.name). \(front.name) is in front now."),
        ]
    }

    // MARK: Events

    static let source = CGEventSource(stateID: .hidSystemState)

    static func post(_ press: MacControl.KeyPress) {
        let flags = CGEventFlags(rawValue: press.flags)
        for down in [true, false] {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: press.code, keyDown: down) else { continue }
            event.flags = flags
            event.post(tap: .cghidEventTap)
        }
    }

    /// Type text as keystrokes: a few characters per event, Return and Tab as keys.
    static func post(text: String) {
        var pending: [UniChar] = []
        func flush() {
            var start = 0
            while start < pending.count {
                var end = min(start + 8, pending.count)
                // Never split a character's surrogate pair.
                if end < pending.count, UTF16.isLeadSurrogate(pending[end - 1]) { end -= 1 }
                let chunk = Array(pending[start..<end])
                for down in [true, false] {
                    guard let event = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down) else { continue }
                    event.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                    event.post(tap: .cghidEventTap)
                }
                usleep(8_000)
                start = end
            }
            pending = []
        }
        for unit in text.utf16 {
            switch unit {
            case 0x0A:
                flush()
                post(MacControl.KeyPress(code: CGKeyCode(kVK_Return), flags: 0, spoken: "Return"))
            case 0x09:
                flush()
                post(MacControl.KeyPress(code: CGKeyCode(kVK_Tab), flags: 0, spoken: "Tab"))
            case 0x0D:
                continue
            default:
                pending.append(unit)
            }
        }
        flush()
    }

    static func post(move point: CGPoint) {
        CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
            .post(tap: .cghidEventTap)
        usleep(30_000)
    }

    static func post(click point: CGPoint) {
        post(move: point)
        for type in [CGEventType.leftMouseDown, .leftMouseUp] {
            CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: .left)?
                .post(tap: .cghidEventTap)
            usleep(20_000)
        }
    }

    static func post(scroll direction: String, lines: Int32) {
        let vertical: Int32 = direction == "up" ? lines : direction == "down" ? -lines : 0
        let horizontal: Int32 = direction == "left" ? lines : direction == "right" ? -lines : 0
        CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 2, wheel1: vertical, wheel2: horizontal, wheel3: 0)?
            .post(tap: .cghidEventTap)
    }
}
