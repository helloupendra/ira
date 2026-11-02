import AppKit
import ApplicationServices
import Foundation

/// What an app's window holds, as a list Ira can read and act on: Accessibility's tree, flattened
/// to the parts a person would point at, each with an id that `mac_click` and `mac_type` take.
/// It does not bring the app forward. A password field's value is never read.
public enum WindowElements {
    public struct Element: Equatable, Sendable {
        public let id: String
        public let kind: String
        public let label: String
        public let value: String?
        public let enabled: Bool
    }

    /// Roles that only hold others, with nothing of their own to point at.
    static let plain: Set<String> = ["AXGroup", "AXScrollArea", "AXSplitGroup", "AXLayoutArea", "AXLayoutItem", "AXUnknown", "AXWebArea", "AXSplitter", "AXScrollBar", "AXWindow", "AXToolbar", "AXList", "AXTable", "AXOutline", "AXTabGroup", "AXValueIndicator"]
    static let words: Set<String> = ["AXStaticText", "AXHeading"]

    public static func kind(_ role: String) -> String {
        if words.contains(role) { return "text" }
        if role == "AXImage" { return "image" }
        return MacControl.kind(role)
    }

    /// The window's elements in reading order (breadth first, then top to bottom, left to right),
    /// at most `limit`; the node of each is for acting on it by id.
    public static func list<N: MacControl.Node>(_ root: N, limit: Int = 200, budget: Int = 4000) -> (elements: [Element], nodes: [String: N], more: Bool) {
        var queue: [(node: N, depth: Int)] = [(root, 0)]
        var at = 0
        var found: [(node: N, label: String)] = []
        while at < queue.count, at < budget {
            let (node, depth) = queue[at]
            at += 1
            if depth > 0, !plain.contains(node.role), let label = node.names.first(where: { !$0.isEmpty }), !label.isEmpty {
                found.append((node, label))
            } else if depth > 0, MacControl.actionable(node), !plain.contains(node.role) {
                found.append((node, ""))  // a field with no name is still a place to type
            }
            if depth < 40 { for child in node.nodes { queue.append((child, depth + 1)) } }
        }
        let ordered = found.enumerated().sorted { a, b in
            let (fa, fb) = (a.element.node.frame ?? .infinite, b.element.node.frame ?? .infinite)
            if abs(fa.minY - fb.minY) > 4 { return fa.minY < fb.minY }
            if fa.minX != fb.minX { return fa.minX < fb.minX }
            return a.offset < b.offset
        }.map(\.element)
        var elements: [Element] = []
        var nodes: [String: N] = [:]
        for (index, entry) in ordered.prefix(limit).enumerated() {
            let id = "e\(index + 1)"
            let secret = MacControl.isSecure(role: entry.node.role, subrole: entry.node.subrole)
            elements.append(Element(
                id: id, kind: kind(entry.node.role), label: String(entry.label.prefix(200)),
                value: secret ? nil : entry.node.shownValue.map { String($0.prefix(200)) }, enabled: entry.node.enabled))
            nodes[id] = entry.node
        }
        return (elements, nodes, ordered.count > limit)
    }

    /// The ids of the last look at each app, for acting on what was seen. They last a minute:
    /// after that a window has moved on, and a click must not land on what was there before.
    final class Seen: @unchecked Sendable {
        static let shared = Seen()
        private let lock = NSLock()
        private var seen: [pid_t: (at: Date, nodes: [String: AXNode])] = [:]
        static let seconds: TimeInterval = 60

        func keep(_ nodes: [String: AXNode], pid: pid_t, now: Date = Date()) {
            lock.withLock { seen[pid] = (now, nodes) }
        }

        func node(_ id: String, pid: pid_t, now: Date = Date()) -> AXNode? {
            lock.withLock {
                guard let kept = seen[pid], now.timeIntervalSince(kept.at) < Seen.seconds else { return nil }
                return kept.nodes[id]
            }
        }
    }

    static let staleID = "that id is from an older look at the window. Look again with window_elements"

    static func json(_ element: Element) -> JSONValue {
        var out: [String: JSONValue] = ["id": .string(element.id), "kind": .string(element.kind), "label": .string(element.label)]
        if let value = element.value { out["value"] = .string(value) }
        if !element.enabled { out["enabled"] = .bool(false) }
        return .object(out)
    }
}
