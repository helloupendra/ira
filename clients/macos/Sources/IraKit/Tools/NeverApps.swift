import Foundation

/// Apps where whatever is typed can run as a command: Terminal and the like, Script Editor,
/// Automator, and Shortcuts (a "Run Shell Script" step). This Mac never opens them for Ira and
/// never types, clicks or presses keys in them, whatever the server asks; the server keeps the
/// same list. Code editors with a terminal of their own (a key opens it) may be opened, but
/// are never typed in either.
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

    /// Editors with a terminal: opened when asked, never typed in.
    public static let editorIDs: Set<String> = [
        "com.microsoft.vscode", "com.microsoft.vscodeinsiders", "com.vscodium", "com.todesktop.230313mzl4w4u92",
        "com.exafunction.windsurf", "dev.zed.zed", "dev.zed.zed-preview", "com.panic.nova", "com.google.android.studio",
    ]
    /// Whole families, by the start of their bundle id: JetBrains' editors all have a terminal.
    public static let editorPrefixes = ["com.jetbrains."]
    public static let editorWords = [
        "visual studio code", "vscodium", "intellij", "pycharm", "webstorm", "phpstorm", "goland", "rubymine", "clion",
        "android studio",
    ]
    /// Names too short or too common to match by part: only the whole name.
    public static let editorNames: Set<String> = ["code", "cursor", "windsurf", "zed", "nova"]

    /// Whether Ira must never type, click or press keys in this app.
    public static func neverType(bundleID: String?, name: String) -> Bool {
        if contains(bundleID: bundleID, name: name) { return true }
        if let bundleID {
            let id = bundleID.lowercased()
            if editorIDs.contains(id) || editorPrefixes.contains(where: { id.hasPrefix($0) }) { return true }
        }
        let lower = name.lowercased()
        return editorNames.contains(lower) || editorWords.contains { lower.contains($0) }
    }

    public static let refusal = "I never open or use Terminal, Script Editor, Automator, Shortcuts or the like: whatever is typed there runs as a command"
    public static let editorRefusal = "I never type in a code editor with a terminal of its own: a key opens the terminal, and whatever is typed there runs as a command"
}
