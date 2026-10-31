import Foundation

/// Apps where whatever is typed can run as a command: Terminal and the like, Script Editor,
/// Automator, and Shortcuts (a "Run Shell Script" step). This Mac never opens them for Ira and
/// never types, clicks or presses keys in them, whatever the server asks; the server keeps the
/// same list.
public enum NeverApps {
    public static let bundleIDs: Set<String> = [
        "com.apple.terminal", "com.googlecode.iterm2", "com.apple.scripteditor2", "com.apple.automator",
        "com.apple.shortcuts", "dev.warp.warp-stable", "com.mitchellh.ghostty", "net.kovidgoyal.kitty",
        "org.alacritty", "com.github.wez.wezterm", "co.zeit.hyper", "org.tabby",
    ]

    /// Matched by any part of the name, erring on the safe side on purpose.
    public static let words = ["terminal", "iterm", "script editor", "automator", "shortcuts"]

    public static func contains(bundleID: String?, name: String) -> Bool {
        if let bundleID, bundleIDs.contains(bundleID.lowercased()) { return true }
        let lower = name.lowercased()
        return words.contains { lower.contains($0) }
    }

    public static let refusal = "I never open or use Terminal, Script Editor, Automator, Shortcuts or the like: whatever is typed there runs as a command"
}
