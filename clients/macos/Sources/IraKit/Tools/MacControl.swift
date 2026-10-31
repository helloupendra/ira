import AppKit
import ApplicationServices
import Carbon.HIToolbox
import Foundation

/// Using the Mac like a person: typing, keys, clicks, scrolling and menus,
/// through macOS Accessibility. Every one is Tier 3 (the person's PIN), works
/// only in an app that is not a password manager or a private part of System
/// Settings, never types into a password field, and answers with what it did
/// and which app is in front now, so Ira can look with `screen_read` before the
/// next step. The answer holds no text from the screen: only Ira's own doing.
///
/// Each call may name its `app` (brought to the front first) and its `task`
/// (the whole job the step belongs to, the same on every step), so that a
/// later approval can cover one task in one app instead of each keystroke.
public enum MacControl {
    // MARK: Permission

    public static var trusted: Bool { AXIsProcessTrusted() }

    /// Whether a control tool may ask macOS to list Ira (off in tests: no dialog).
    nonisolated(unsafe) public static var mayPrompt = true

    /// Ask macOS to list Ira under Accessibility; it shows its own dialog.
    @discardableResult
    public static func requestTrust() -> Bool {
        let prompt = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        return AXIsProcessTrustedWithOptions([prompt: true] as CFDictionary)
    }

    public static let notTrusted =
        "Accessibility is off for Ira, so I cannot use this Mac's keyboard or mouse. Switch Ira on in System Settings → Privacy & Security → Accessibility, then ask again"

    /// Ira is about to type or click: its own window lets go of the keyboard.
    public static let acting = Notification.Name("in.ira.mac.acting")
    public static let acted = Notification.Name("in.ira.mac.acted")

    // MARK: Where Ira never acts

    /// System Settings pages Ira may work in: everyday ones. Privacy, security,
    /// passwords, accounts, sharing, network and anything else are refused.
    public static let everydaySettings: Set<String> = [
        "Appearance", "Displays", "Sound", "Wallpaper", "Screen Saver", "Focus", "Notifications", "Battery",
        "Desktop & Dock", "Control Centre", "Control Center", "Keyboard", "Trackpad", "Mouse", "Wi-Fi", "Wi‑Fi",
        "Bluetooth", "Date & Time", "Language & Region", "Siri", "Apple Intelligence & Siri", "Spotlight", "Menu Bar",
    ]

    /// Why Ira will not act in this app's front window, or nil.
    public static func refusal(bundleID: String?, app: String, window: String?) -> String? {
        if let bundleID, bundleID.hasPrefix("in.ira.mac") {
            return "Ira's own window is in front. Say which app to use"
        }
        if bundleID == "com.apple.systempreferences" {
            if let window, everydaySettings.contains(window) { return nil }
            return "I don't work in System Settings' \(window.map { "“\($0)” page" } ?? "window") myself: only on everyday pages such as Appearance, Displays, Sound or Notifications. Privacy, security, passwords and accounts stay yours"
        }
        if NeverApps.contains(bundleID: bundleID, name: app) {
            return NeverApps.refusal
        }
        if let bundleID, ScreenText.systemUI.contains(bundleID) {
            return "a macOS prompt is in front (\(app)). Answer it yourself"
        }
        if let bundleID, let known = ScreenText.neverRead[bundleID] {
            return "I never use \(known): it holds passwords"
        }
        return nil
    }

    /// Roles of a password field: Ira never types there.
    public static func isSecure(role: String?, subrole: String?) -> Bool {
        role == "AXSecureTextField" || subrole == "AXSecureTextField"
    }

    // MARK: Keys

    public struct KeyPress: Equatable, Sendable {
        public let code: CGKeyCode
        public let flags: UInt64
        /// As said back: "Command-L".
        public let spoken: String
    }

    static let modifierNames: [String: (flag: CGEventFlags, spoken: String)] = [
        "cmd": (.maskCommand, "Command"), "command": (.maskCommand, "Command"),
        "shift": (.maskShift, "Shift"),
        "opt": (.maskAlternate, "Option"), "option": (.maskAlternate, "Option"), "alt": (.maskAlternate, "Option"),
        "ctrl": (.maskControl, "Control"), "control": (.maskControl, "Control"),
        "fn": (.maskSecondaryFn, "Fn"),
    ]

    static let keyNames: [String: (code: Int, spoken: String)] = {
        var keys: [String: (Int, String)] = [
            "return": (kVK_Return, "Return"), "enter": (kVK_Return, "Return"), "tab": (kVK_Tab, "Tab"),
            "space": (kVK_Space, "Space"), "esc": (kVK_Escape, "Escape"), "escape": (kVK_Escape, "Escape"),
            "delete": (kVK_Delete, "Delete"), "backspace": (kVK_Delete, "Delete"),
            "forwarddelete": (kVK_ForwardDelete, "Forward Delete"),
            "up": (kVK_UpArrow, "Up"), "down": (kVK_DownArrow, "Down"), "left": (kVK_LeftArrow, "Left"),
            "right": (kVK_RightArrow, "Right"), "home": (kVK_Home, "Home"), "end": (kVK_End, "End"),
            "pageup": (kVK_PageUp, "Page Up"), "pagedown": (kVK_PageDown, "Page Down"),
            "-": (kVK_ANSI_Minus, "-"), "minus": (kVK_ANSI_Minus, "-"), "=": (kVK_ANSI_Equal, "="),
            "plus": (kVK_ANSI_Equal, "="), "[": (kVK_ANSI_LeftBracket, "["), "]": (kVK_ANSI_RightBracket, "]"),
            ";": (kVK_ANSI_Semicolon, ";"), "'": (kVK_ANSI_Quote, "'"), ",": (kVK_ANSI_Comma, ","),
            ".": (kVK_ANSI_Period, "."), "/": (kVK_ANSI_Slash, "/"), "\\": (kVK_ANSI_Backslash, "\\"),
            "`": (kVK_ANSI_Grave, "`"),
        ]
        let letters: [(String, Int)] = [
            ("a", kVK_ANSI_A), ("b", kVK_ANSI_B), ("c", kVK_ANSI_C), ("d", kVK_ANSI_D), ("e", kVK_ANSI_E),
            ("f", kVK_ANSI_F), ("g", kVK_ANSI_G), ("h", kVK_ANSI_H), ("i", kVK_ANSI_I), ("j", kVK_ANSI_J),
            ("k", kVK_ANSI_K), ("l", kVK_ANSI_L), ("m", kVK_ANSI_M), ("n", kVK_ANSI_N), ("o", kVK_ANSI_O),
            ("p", kVK_ANSI_P), ("q", kVK_ANSI_Q), ("r", kVK_ANSI_R), ("s", kVK_ANSI_S), ("t", kVK_ANSI_T),
            ("u", kVK_ANSI_U), ("v", kVK_ANSI_V), ("w", kVK_ANSI_W), ("x", kVK_ANSI_X), ("y", kVK_ANSI_Y),
            ("z", kVK_ANSI_Z), ("0", kVK_ANSI_0), ("1", kVK_ANSI_1), ("2", kVK_ANSI_2), ("3", kVK_ANSI_3),
            ("4", kVK_ANSI_4), ("5", kVK_ANSI_5), ("6", kVK_ANSI_6), ("7", kVK_ANSI_7), ("8", kVK_ANSI_8),
            ("9", kVK_ANSI_9),
        ]
        for (name, code) in letters { keys[name] = (code, name.uppercased()) }
        let functionKeys = [kVK_F1, kVK_F2, kVK_F3, kVK_F4, kVK_F5, kVK_F6, kVK_F7, kVK_F8, kVK_F9, kVK_F10, kVK_F11, kVK_F12]
        for (index, code) in functionKeys.enumerated() { keys["f\(index + 1)"] = (code, "F\(index + 1)") }
        return keys.mapValues { (code: $0.0, spoken: $0.1) }
    }()

    public static let maxPresses = 12

    /// "cmd+l return", "cmd+shift+t, esc", "down down return": presses in order.
    public static func parseKeys(_ text: String) throws -> [KeyPress] {
        let combos = text.lowercased()
            .replacingOccurrences(of: ",", with: " ")
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)
        guard !combos.isEmpty else { throw ToolFailure("say which keys to press, e.g. cmd+l or return") }
        guard combos.count <= maxPresses else { throw ToolFailure("at most \(maxPresses) presses at a time") }
        return try combos.map { combo in
            // "cmd++" is Command and the = key; otherwise "+" joins the parts.
            var parts = combo.split(separator: "+", omittingEmptySubsequences: true).map(String.init)
            if combo.hasSuffix("++") { parts.append("plus") }
            guard let last = parts.popLast() else { throw ToolFailure("“\(combo)” is not a key") }
            var flags = CGEventFlags()
            var spoken: [String] = []
            for name in parts {
                guard let modifier = modifierNames[name] else {
                    throw ToolFailure("“\(name)” in “\(combo)” is not cmd, shift, option, ctrl or fn")
                }
                flags.insert(modifier.flag)
                if !spoken.contains(modifier.spoken) { spoken.append(modifier.spoken) }
            }
            guard let key = keyNames[last] else {
                throw ToolFailure("“\(last)” is not a key I know: use letters, digits, return, tab, space, esc, delete, up, down, left, right, home, end, pageup, pagedown or f1–f12")
            }
            return KeyPress(code: CGKeyCode(key.code), flags: flags.rawValue, spoken: (spoken + [key.spoken]).joined(separator: "-"))
        }
    }

    // MARK: Finding a control by its label

    /// What the finder needs from an element in an app's window.
    public protocol Node {
        var role: String { get }
        var subrole: String? { get }
        /// Its label as shown or as described for VoiceOver: title, description,
        /// placeholder, identifier, a button's value, its label's text.
        var names: [String] { get }
        var enabled: Bool { get }
        var actions: [String] { get }
        var frame: CGRect? { get }
        var nodes: [Self] { get }
        /// The same element of the app, reached another way.
        func isSame(_ other: Self) -> Bool
    }

    /// The kinds of control a person names, by their roles.
    public static let roles: [String: Set<String>] = [
        "button": ["AXButton", "AXMenuButton", "AXPopUpButton", "AXDisclosureTriangle"],
        "link": ["AXLink"],
        "field": ["AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"],
        "checkbox": ["AXCheckBox", "AXSwitch", "AXToggle"],
        "tab": ["AXTab", "AXTabButton", "AXRadioButton"],
        "menu": ["AXMenuButton", "AXPopUpButton", "AXComboBox"],
        "row": ["AXRow", "AXCell", "AXOutlineRow"],
    ]

    static let textRoles: Set<String> = ["AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"]
    static let pressActions = ["AXPress", "AXConfirm", "AXPick", "AXOpen"]

    public struct Match<N: Node> {
        public let node: N
        public let score: Int
        public let label: String
        /// False for words with no control around them: clicked where they are.
        public var actionable = true
    }

    static func normal(_ text: String) -> String {
        text.lowercased()
            .replacingOccurrences(of: "…", with: "")
            .replacingOccurrences(of: "...", with: "")
            .split(whereSeparator: { $0.isWhitespace || $0 == ":" })
            .joined(separator: " ")
    }

    /// How well a name fits the label: 3 the same, 2 begins with it, 1 holds it as words.
    static func fit(_ name: String, _ label: String) -> Int {
        let name = normal(name)
        let label = normal(label)
        guard !name.isEmpty, !label.isEmpty else { return 0 }
        if name == label { return 3 }
        if name.hasPrefix(label + " ") { return 2 }
        if (" " + name + " ").contains(" " + label + " ") { return 1 }
        return 0
    }

    static func actionable<N: Node>(_ node: N) -> Bool {
        textRoles.contains(node.role) || ["AXRow", "AXCell", "AXOutlineRow"].contains(node.role)
            || node.actions.contains(where: pressActions.contains)
    }

    /// Controls in `root` whose name fits `label`, best first, then top to bottom.
    /// Text inside a button counts as the button's. At most `budget` elements are looked at.
    public static func find<N: Node>(_ label: String, role: String?, in root: N, budget: Int = 4000) -> [Match<N>] {
        let wanted = role.flatMap { roles[$0] }
        var queue: [(node: N, owner: N?, depth: Int)] = [(root, nil, 0)]
        var seen = 0
        var found: [Match<N>] = []
        var index = 0
        while index < queue.count, seen < budget {
            let (node, owner, depth) = queue[index]
            index += 1
            seen += 1
            let own = actionable(node) ? node : owner
            let score = node.names.map { fit($0, label) }.max() ?? 0
            let name = node.names.first(where: { fit($0, label) == score }) ?? label
            if score > 0, let target = own, wanted.map({ $0.contains(target.role) || $0.contains(target.subrole ?? "") }) ?? true {
                found.append(Match(node: target, score: score, label: name))
            } else if score > 0, own == nil, wanted == nil, depth > 0, ["AXStaticText", "AXImage", "AXHeading"].contains(node.role),
                node.frame.map({ $0.width > 0 && $0.height > 0 }) == true
            {
                // Words a page reacts to without saying so (a script's click): their place is known.
                found.append(Match(node: node, score: score, label: name, actionable: false))
            }
            if depth < 40 {
                for child in node.nodes { queue.append((child, own, depth + 1)) }
            }
        }
        // One control found through several of its parts counts once, at its best.
        var best: [Match<N>] = []
        for match in found {
            if let at = best.firstIndex(where: { $0.node.isSame(match.node) }) {
                if match.score > best[at].score { best[at] = match }
            } else {
                best.append(match)
            }
        }
        return best.sorted { a, b in
            if a.score != b.score { return a.score > b.score }
            if a.actionable != b.actionable { return a.actionable }
            if a.node.enabled != b.node.enabled { return a.node.enabled }
            let (fa, fb) = (a.node.frame ?? .zero, b.node.frame ?? .zero)
            return fa.minY != fb.minY ? fa.minY < fb.minY : fa.minX < fb.minX
        }
    }

    /// The matches worth acting on: the best ones, or the one `index` picks among them.
    public static func choose<N: Node>(_ matches: [Match<N>], index: Int?) -> Result<Match<N>, ToolFailure> {
        guard let top = matches.first else { return .failure(ToolFailure("not found")) }
        let best = matches.filter {
            $0.score == top.score && $0.actionable == top.actionable && $0.node.enabled == top.node.enabled
        }
        if let index {
            guard (1...best.count).contains(index) else {
                return .failure(ToolFailure("there \(best.count == 1 ? "is one" : "are \(best.count)") of those; index goes from 1 to \(best.count)"))
            }
            return .success(best[index - 1])
        }
        if best.count > 1 {
            let kinds = Set(best.map { kind($0.node.role) })
            let what = kinds.count == 1 ? kinds.first! + "s" : "controls"
            return .failure(ToolFailure("I found \(best.count) \(what) called “\(top.label)”. Say which with index, 1 for the one nearest the top"))
        }
        return .success(top)
    }

    /// A role in words.
    public static func kind(_ role: String) -> String {
        switch role {
        case "AXButton", "AXMenuButton", "AXPopUpButton", "AXDisclosureTriangle": return "button"
        case "AXLink": return "link"
        case "AXTextField", "AXTextArea", "AXComboBox", "AXSearchField": return "field"
        case "AXSecureTextField": return "password field"
        case "AXCheckBox", "AXSwitch", "AXToggle": return "checkbox"
        case "AXTab", "AXTabButton", "AXRadioButton": return "tab"
        case "AXRow", "AXCell", "AXOutlineRow": return "row"
        case "AXMenuItem": return "menu item"
        default: return "control"
        }
    }

    // MARK: Menus

    /// "File > New Window", "View → Show Sidebar": the titles from the menu bar down.
    public static func menuPath(_ text: String) throws -> [String] {
        let parts = text.replacingOccurrences(of: "→", with: ">")
            .split(separator: ">")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        guard parts.count >= 2 else { throw ToolFailure("give the menu and the item, e.g. File > New Window") }
        guard parts.count <= 5 else { throw ToolFailure("a menu path has at most 5 steps") }
        if ["apple", ""].contains(normal(parts[0])) {
            throw ToolFailure("I never use the Apple menu (shut down, restart, log out): those stay yours")
        }
        return parts
    }

    /// The item among `titles` that `wanted` names: the same title, else the one it begins.
    public static func pick(_ wanted: String, among titles: [String]) -> Int? {
        if let same = titles.firstIndex(where: { fit($0, wanted) == 3 }) { return same }
        let begins = titles.indices.filter { fit(titles[$0], wanted) == 2 }
        return begins.count == 1 ? begins[0] : nil
    }

    // MARK: Arguments

    public struct Step {
        public let app: String?
        public let task: String?
    }

    static func step(_ args: ToolArgs) throws -> Step {
        Step(app: try args.text("app", limit: 100), task: try args.text("task", limit: 200))
    }
}

/// An element of another app's window, read through Accessibility.
public struct AXNode: MacControl.Node, @unchecked Sendable {
    public let element: AXUIElement

    public init(_ element: AXUIElement) {
        self.element = element
    }

    func value(_ attribute: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else { return nil }
        return value
    }

    func string(_ attribute: String) -> String? {
        (value(attribute) as? String).flatMap { $0.isEmpty ? nil : $0 }
    }

    func node(_ attribute: String) -> AXNode? {
        guard let value = value(attribute), CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return AXNode(value as! AXUIElement)
    }

    public var role: String { string(kAXRoleAttribute) ?? "" }
    public var subrole: String? { string(kAXSubroleAttribute) }

    public var names: [String] {
        var names = [kAXTitleAttribute, kAXDescriptionAttribute, "AXPlaceholderValue", kAXHelpAttribute, "AXIdentifier"]
            .compactMap(string)
        // A button's or a link's text is its value; a field's value is what was typed, never a name.
        if !MacControl.textRoles.contains(role), let value = string(kAXValueAttribute), value.count <= 200 {
            names.append(value)
        }
        if let label = node(kAXTitleUIElementAttribute)?.string(kAXValueAttribute) { names.append(label) }
        return names
    }

    public var enabled: Bool { (value(kAXEnabledAttribute) as? Bool) ?? true }

    public var actions: [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
        return (names as? [String]) ?? []
    }

    public var frame: CGRect? {
        guard let position = value(kAXPositionAttribute), let size = value(kAXSizeAttribute),
            CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(size) == AXValueGetTypeID()
        else { return nil }
        var point = CGPoint.zero
        var extent = CGSize.zero
        guard AXValueGetValue(position as! AXValue, .cgPoint, &point), AXValueGetValue(size as! AXValue, .cgSize, &extent) else {
            return nil
        }
        return CGRect(origin: point, size: extent)
    }

    public func isSame(_ other: AXNode) -> Bool { CFEqual(element, other.element) }

    public var nodes: [AXNode] {
        guard let children = value(kAXChildrenAttribute) as? [AXUIElement] else { return [] }
        return children.map(AXNode.init)
    }

    var focused: AXNode? { node(kAXFocusedUIElementAttribute) }
    var focusedWindow: AXNode? { node(kAXFocusedWindowAttribute) ?? node(kAXMainWindowAttribute) }

    var pid: pid_t {
        var pid: pid_t = 0
        AXUIElementGetPid(element, &pid)
        return pid
    }

    @discardableResult
    func set(_ attribute: String, _ value: CFTypeRef) -> Bool {
        AXUIElementSetAttributeValue(element, attribute as CFString, value) == .success
    }

    @discardableResult
    func perform(_ action: String) -> Bool {
        AXUIElementPerformAction(element, action as CFString) == .success
    }
}
