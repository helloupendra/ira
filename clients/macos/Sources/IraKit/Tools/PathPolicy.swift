import Foundation

/// Which files Ira may find, read and open on this Mac.
///
/// * Only inside the allowed folders: the home folder by default, narrowed to
///   chosen folders if the person picks some, plus any folders outside the home
///   folder they add.
/// * Never the explicit deny list below, wherever it is: `~/Library` (the
///   Keychain, mail, messages, browser data), credential folders such as
///   `~/.ssh` and `~/.aws`, key files, and any hidden file or folder.
/// * Symbolic links are followed first, so a link on the Desktop to `~/.ssh`
///   is refused like `~/.ssh` itself.
public struct PathPolicy: Sendable {
    public let home: URL
    public let roots: [URL]

    /// Folders under the home folder that are never read, listed or opened.
    public static let deniedHomeFolders = [
        "Library",
        ".ssh", ".aws", ".gnupg", ".gpg", ".config", ".kube", ".docker", ".azure",
        ".gcloud", ".terraform.d", ".password-store", ".local", ".cache", ".Trash",
    ]

    /// File names that are never read, wherever they are.
    public static let deniedNames: Set<String> = [
        ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".vault-token", ".pgpass",
        ".my.cnf", ".zsh_history", ".bash_history", ".python_history", ".env",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "known_hosts",
        "authorized_keys",
    ]

    /// File extensions that hold keys or keychains.
    public static let deniedExtensions: Set<String> = [
        "pem", "key", "p12", "pfx", "keychain", "keychain-db", "kdbx", "ppk", "gpg", "asc",
        "jks", "keystore", "mobileprovision", "ovpn",
    ]

    /// Folders outside the home folder that are never allowed, even if added.
    public static let deniedSystemFolders = [
        "/System", "/Library/Keychains", "/Library/Security", "/private/etc", "/private/var/db",
        "/private/var/root", "/private/var/protected", "/etc", "/var/db", "/var/root", "/usr",
        "/bin", "/sbin", "/dev", "/cores", "/Network",
    ]

    /// - Parameters:
    ///   - home: the person's home folder.
    ///   - only: when not empty, Ira looks only inside these folders.
    ///   - extra: folders outside the home folder Ira may also use.
    public init(home: URL, only: [String] = [], extra: [String] = []) {
        let home = PathPolicy.resolve(home)
        self.home = home
        let chosen = only.compactMap { PathPolicy.expand($0, home: home) }.map(PathPolicy.resolve)
        let added = extra.compactMap { PathPolicy.expand($0, home: home) }.map(PathPolicy.resolve)
        self.roots = (chosen.isEmpty ? [home] : chosen) + added
    }

    public static func current(settings: AppSettings) -> PathPolicy {
        PathPolicy(
            home: FileManager.default.homeDirectoryForCurrentUser,
            only: settings.onlyFolders, extra: settings.extraFolders)
    }

    /// `~/x` or an absolute path as a URL; nil for anything relative.
    public static func expand(_ path: String, home: URL) -> URL? {
        let path = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if path == "~" { return home }
        if path.hasPrefix("~/") {
            return home.appendingPathComponent(String(path.dropFirst(2)))
        }
        if path.hasPrefix("/") { return URL(fileURLWithPath: path) }
        return nil
    }

    /// The real path: links resolved, even when the last parts do not exist yet
    /// (a link to a folder, then a file name inside it).
    static func resolve(_ url: URL) -> URL {
        var existing = url.standardizedFileURL
        var rest: [String] = []
        while !FileManager.default.fileExists(atPath: existing.path), existing.pathComponents.count > 1 {
            rest.insert(existing.lastPathComponent, at: 0)
            existing.deleteLastPathComponent()
        }
        var real = existing.resolvingSymlinksInPath()
        for part in rest { real.appendPathComponent(part) }
        return real.standardizedFileURL
    }

    /// Why a path may not be used, or nil when it may.
    public func refusal(_ path: String) -> String? {
        guard let url = PathPolicy.expand(path, home: home) else {
            return "give the full path, starting with / or ~/"
        }
        // Check the path as written and where its links lead: both must pass.
        let written = url.standardizedFileURL
        let real = PathPolicy.resolve(url)
        for candidate in [written, real] {
            if let reason = deniedReason(candidate) { return reason }
        }
        guard roots.contains(where: { PathPolicy.isInside(real, $0) }) else {
            return "that is outside the folders Ira may use on this Mac"
        }
        return nil
    }

    public func allows(_ path: String) -> Bool {
        refusal(path) == nil
    }

    private func deniedReason(_ url: URL) -> String? {
        let path = url.path
        // The Mac's disk ignores case, so ~/LIBRARY is ~/Library: the deny list does too.
        let inHome = PathPolicy.isInside(url, home, ignoringCase: true)
        for folder in PathPolicy.deniedSystemFolders
        where !inHome && PathPolicy.isInside(url, URL(fileURLWithPath: folder), ignoringCase: true) {
            return "Ira never reads system folders"
        }
        // Inside the home folder: the denied folders, by their first component.
        if inHome {
            let relative = String(path.dropFirst(home.path.count)).split(separator: "/").map(String.init)
            if let first = relative.first,
                let denied = PathPolicy.deniedHomeFolders.first(where: { $0.caseInsensitiveCompare(first) == .orderedSame })
            {
                return "Ira never reads ~/\(denied)"
            }
        }
        let components = inHome ? Array(url.pathComponents.dropFirst(home.pathComponents.count)) : url.pathComponents
        if components.contains(where: { $0.hasPrefix(".") && $0 != "." && $0 != ".." }) {
            return "Ira never reads hidden files or folders"
        }
        let name = url.lastPathComponent.lowercased()
        if PathPolicy.deniedNames.contains(name) || name.hasPrefix(".env") || name.hasPrefix("id_rsa")
            || name.hasPrefix("id_ed25519")
        {
            return "Ira never reads files that hold passwords or keys"
        }
        if PathPolicy.deniedExtensions.contains(url.pathExtension.lowercased()) {
            return "Ira never reads key or keychain files"
        }
        return nil
    }

    static func isInside(_ url: URL, _ folder: URL, ignoringCase: Bool = false) -> Bool {
        var path = url.standardizedFileURL.path
        var base = folder.standardizedFileURL.path
        if ignoringCase {
            path = path.lowercased()
            base = base.lowercased()
        }
        if base == "/" { return true }
        return path == base || path.hasPrefix(base.hasSuffix("/") ? base : base + "/")
    }

    /// A path for people: the home folder as `~`.
    public func display(_ url: URL) -> String {
        let path = url.standardizedFileURL.path
        if PathPolicy.isInside(url, home) {
            let rest = String(path.dropFirst(home.path.count))
            return "~" + rest
        }
        return path
    }
}
