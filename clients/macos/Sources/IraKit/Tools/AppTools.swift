import AppKit
import Foundation

/// Apps, links, VS Code, the clipboard and Shortcuts.
///
/// * `app_open` (Tier 1) and `vscode_open` (Tier 1): open an app, or a folder
///   in VS Code; Ira says it did;
/// * `url_open` (Tier 2): a web page, read back first;
/// * `clipboard_read` (Tier 0, `clipboard` skill): only when asked, and never
///   what a password manager marked as a password;
/// * `shortcuts_list` (Tier 0), `shortcuts_run` (Tier 2): the person's own
///   Shortcuts, which can do anything they built them to.
public enum AppTools {
    static let appFolders = [
        "/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities",
    ]

    /// The best match for an app's name among `names` (without ".app"): exact,
    /// then the start of a name, then anywhere in it; nil if none or unclear.
    public static func bestApp(_ wanted: String, among names: [String]) -> String? {
        let key = wanted.lowercased().replacingOccurrences(of: ".app", with: "").trimmingCharacters(in: .whitespaces)
        guard !key.isEmpty else { return nil }
        if let exact = names.first(where: { $0.lowercased() == key }) { return exact }
        let prefixed = names.filter { $0.lowercased().hasPrefix(key) }.sorted { $0.count < $1.count }
        if let first = prefixed.first { return first }
        let containing = names.filter { $0.lowercased().contains(key) }.sorted { $0.count < $1.count }
        return containing.first
    }

    static func installedApps(home: URL) -> [String: URL] {
        var apps: [String: URL] = [:]
        let folders = appFolders.map { URL(fileURLWithPath: $0) } + [home.appendingPathComponent("Applications")]
        for folder in folders {
            let items = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
            for item in items where item.pathExtension == "app" {
                let name = item.deletingPathExtension().lastPathComponent
                if apps[name] == nil { apps[name] = item }
            }
        }
        return apps
    }

    public static func appOpen(_ raw: JSONValue, home: URL) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["name"])
        let wanted = try args.required("name", limit: 100, what: "which app (its name)")
        var url: URL?
        if wanted.contains("."), !wanted.lowercased().hasSuffix(".app") {
            url = await MainActor.run { NSWorkspace.shared.urlForApplication(withBundleIdentifier: wanted) }
        }
        if url == nil {
            let apps = installedApps(home: home)
            url = bestApp(wanted, among: Array(apps.keys)).flatMap { apps[$0] }
        }
        guard let url else { throw ToolFailure("no app called \(wanted) is installed on this Mac") }
        let name = url.deletingPathExtension().lastPathComponent
        do {
            _ = try await NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        } catch {
            throw ToolFailure("\(name) did not open: \(error.localizedDescription)")
        }
        return ["opened": .string(name), "summary": .string("Opened \(name).")]
    }

    /// An http(s) address with a host, or nil.
    public static func webURL(_ text: String) -> URL? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let withScheme = trimmed.contains("://") ? trimmed : "https://" + trimmed
        guard let url = URL(string: withScheme), let scheme = url.scheme?.lowercased(),
            ["http", "https"].contains(scheme), let host = url.host, host.contains(".") || host == "localhost"
        else { return nil }
        return url
    }

    public static func urlOpen(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["url"])
        let text = try args.required("url", limit: 2000, what: "which address (url)")
        guard let url = webURL(text) else { throw ToolFailure("I open only web addresses (http or https)") }
        let opened = await MainActor.run { NSWorkspace.shared.open(url) }
        guard opened else { throw ToolFailure("macOS could not open it") }
        return ["opened": .string(url.host ?? ""), "summary": .string("Opened \(url.host ?? "the page") in your browser.")]
    }

    // MARK: VS Code

    static let vscodeIDs = ["com.microsoft.VSCode", "com.microsoft.VSCodeInsiders", "com.vscodium"]

    static func vscode() async -> URL? {
        await MainActor.run {
            for id in vscodeIDs {
                if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: id) { return url }
            }
            return nil
        }
    }

    /// The link that opens an editor extension with a prompt filled in, from a
    /// template in the local settings: `{prompt}` is replaced, URL-encoded.
    public static func promptLink(template: String, prompt: String) -> URL? {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+#?")
        guard template.contains("{prompt}"),
            let encoded = prompt.addingPercentEncoding(withAllowedCharacters: allowed)
        else { return nil }
        return URL(string: template.replacingOccurrences(of: "{prompt}", with: encoded))
    }

    public static func vscodeOpen(_ raw: JSONValue, policy: PathPolicy, promptTemplate: String?) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["path", "prompt"])
        let path = try args.required("path", limit: 2000, what: "which folder or file (path)")
        if let refusal = policy.refusal(path) { throw ToolFailure(refusal) }
        guard let url = PathPolicy.expand(path, home: policy.home), FileManager.default.fileExists(atPath: url.path) else {
            throw ToolFailure("there is nothing at that path")
        }
        let prompt = try args.text("prompt", limit: 4000)
        try await openInVSCode(url)
        var summary = "Opened \(url.lastPathComponent) in VS Code."
        if let prompt {
            if let template = promptTemplate, let link = promptLink(template: template, prompt: prompt) {
                try? await Task.sleep(nanoseconds: 1_500_000_000)  // let the window open first
                _ = await MainActor.run { NSWorkspace.shared.open(link) }
                summary += " The request is filled in there; press Return in VS Code to send it."
            } else {
                summary += " No editor extension link is set up on this Mac, so type the request there."
            }
        }
        return ["opened": .string(url.path), "summary": .string(summary)]
    }

    public static func openInVSCode(_ url: URL) async throws {
        guard let app = await vscode() else { throw ToolFailure("VS Code is not installed on this Mac") }
        do {
            _ = try await NSWorkspace.shared.open([url], withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration())
        } catch {
            throw ToolFailure("VS Code did not open: \(error.localizedDescription)")
        }
    }

    // MARK: Clipboard

    /// Types password managers put on the pasteboard to say "do not keep or read this"
    /// (the nspasteboard.org conventions).
    public static let privateTypes: Set<String> = [
        "org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType", "org.nspasteboard.AutoGeneratedType",
        "com.agilebits.onepassword",
    ]

    public static func isPrivate(_ types: [String]) -> Bool {
        types.contains(where: privateTypes.contains)
    }

    public static func clipboardRead(_ raw: JSONValue) async throws -> JSONValue {
        _ = try ToolArgs(raw, allowed: [])
        let (types, text, files) = await MainActor.run { () -> ([String], String?, [String]) in
            let board = NSPasteboard.general
            let types = (board.types ?? []).map(\.rawValue)
            let files = (board.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? [])
                .map(\.lastPathComponent)
            return (types, board.string(forType: .string), files)
        }
        if isPrivate(types) { throw ToolFailure("the clipboard holds something a password manager marked as private; I do not read it") }
        if let text, !text.isEmpty {
            let cut = FileText.cut(text, kind: "clipboard", maxChars: Toolbox.maxText)
            return ["text": .string(cut.text), "truncated": .bool(cut.truncated), "summary": .string("The clipboard holds \(cut.text.count) characters of text.")]
        }
        if !files.isEmpty {
            return ["files": .array(files.map { .string($0) }), "summary": .string("The clipboard holds \(files.count) file\(files.count == 1 ? "" : "s"): \(files.prefix(5).joined(separator: ", ")).")]
        }
        if types.contains(where: { $0.contains("image") || $0.contains("png") || $0.contains("tiff") }) {
            return ["summary": "The clipboard holds a picture, not text."]
        }
        return ["summary": "The clipboard is empty."]
    }

    // MARK: Shortcuts

    static let shortcuts = "/usr/bin/shortcuts"

    public static func shortcutsList(_ raw: JSONValue) async throws -> JSONValue {
        _ = try ToolArgs(raw, allowed: [])
        let result = try await Command.run([shortcuts, "list"], timeout: 15)
        guard result.status == 0 else { throw ToolFailure("Shortcuts did not answer") }
        let names = result.stdout.split(separator: "\n").map(String.init).filter { !$0.isEmpty }.prefix(200)
        return [
            "shortcuts": .array(names.map { .string($0) }),
            "summary": .string(names.isEmpty ? "No shortcuts yet." : "\(names.count) shortcuts: \(names.prefix(10).joined(separator: ", ")).")
        ]
    }

    public static func shortcutsRun(_ raw: JSONValue) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["name", "input"])
        let name = try args.required("name", limit: 200, what: "which shortcut (its name)")
        let input = try args.text("input", limit: 20_000)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("ira-shortcut-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        var argv = [shortcuts, "run", name, "--output-path", folder.appendingPathComponent("out").path, "--output-type", "public.plain-text"]
        if let input {
            let file = folder.appendingPathComponent("in.txt")
            try input.write(to: file, atomically: true, encoding: .utf8)
            argv += ["--input-path", file.path]
        }
        let result = try await Command.run(argv, timeout: 20)
        if result.timedOut { throw ToolFailure("the shortcut \(name) was still running after 20 seconds; it goes on by itself") }
        guard result.status == 0 else {
            let reason = result.stderr.split(separator: "\n").last.map(String.init) ?? "it failed"
            throw ToolFailure("the shortcut \(name) did not run: \(reason.prefix(200))")
        }
        let output = (try? String(contentsOf: folder.appendingPathComponent("out"), encoding: .utf8)) ?? ""
        let cut = FileText.cut(output, kind: "shortcut", maxChars: 4000)
        var content: [String: JSONValue] = ["ran": .string(name), "summary": .string("Ran the shortcut \(name).")]
        if !cut.text.isEmpty { content["output"] = .string(cut.text) }
        return .object(content)
    }
}
