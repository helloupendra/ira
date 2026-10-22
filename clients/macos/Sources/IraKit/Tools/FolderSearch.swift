import Foundation

/// Finding a folder by what a person calls it: "invoicereminder service" or
/// "Invoicereminder servise" for `invoice-reminder-service`.
///
/// Names are split into words (at `-`, `_`, `.`, spaces and lower-to-upper
/// case changes). Each word of the request must match a word of the name: the
/// same word, the start of one, two neighbouring words run together ("invoice" +
/// "reminder"), or the same word with a typo or two. Exact names rank first,
/// then prefixes, then the rest.
public enum FolderMatch {
    /// The words of a name or a request, lower case.
    public static func words(_ text: String) -> [String] {
        var words: [String] = []
        var current = ""
        var previousLower = false
        for character in text {
            if character.isLetter || character.isNumber {
                if character.isUppercase && previousLower && !current.isEmpty {
                    words.append(current)
                    current = ""
                }
                current.append(contentsOf: character.lowercased())
                previousLower = character.isLowercase
            } else {
                if !current.isEmpty { words.append(current) }
                current = ""
                previousLower = false
            }
        }
        if !current.isEmpty { words.append(current) }
        return words
    }

    static func distance(_ a: String, _ b: String) -> Int {
        let a = Array(a), b = Array(b)
        if a.isEmpty { return b.count }
        if b.isEmpty { return a.count }
        var previous = Array(0...b.count)
        for i in 1...a.count {
            var current = [i] + Array(repeating: 0, count: b.count)
            for j in 1...b.count {
                current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1))
            }
            previous = current
        }
        return previous[b.count]
    }

    static func closeEnough(_ a: String, _ b: String) -> Bool {
        let longest = max(a.count, b.count)
        guard longest >= 4 else { return a == b }
        return distance(a, b) <= (longest >= 7 ? 2 : 1)
    }

    /// How well one word of a request matches a name's words (0: not at all).
    static func wordScore(_ word: String, _ name: [String]) -> Double {
        var best = 0.0
        for (index, part) in name.enumerated() {
            if part == word { return 1 }
            if word.count >= 3, part.hasPrefix(word) { best = max(best, 0.9) }
            // Two neighbouring words run together: "invoice" + "reminder" in "invoicereminder".
            if index + 1 < name.count {
                let next = name[index + 1]
                for cut in stride(from: min(word.count - 1, part.count), through: 2, by: -1) {
                    let head = String(word.prefix(cut)), tail = String(word.dropFirst(cut))
                    if part.hasPrefix(head), !tail.isEmpty, next.hasPrefix(tail) || closeEnough(tail, next) {
                        best = max(best, 0.8)
                        break
                    }
                }
            }
            if closeEnough(word, part) { best = max(best, 0.7) }
            if word.count >= 4, part.count >= 4, closeEnough(String(word.prefix(part.count)), part) {
                best = max(best, 0.6)
            }
        }
        return best
    }

    /// The score of a name for a request, or nil when some word of the request
    /// matches nothing. 2 and more: the same name; about 1: every word matched.
    public static func score(query: String, name: String) -> Double? {
        let wanted = words(query), have = words(name)
        guard !wanted.isEmpty, !have.isEmpty else { return nil }
        if wanted.joined() == have.joined() { return 2 }
        var total = 0.0
        for word in wanted {
            let score = wordScore(word, have)
            guard score > 0 else { return nil }
            total += score
        }
        let average = total / Double(wanted.count)
        // A name that holds more besides counts a little less.
        let extra = Double(max(0, have.count - wanted.count)) * 0.02
        return max(0.01, average - extra) + (have.joined().hasPrefix(wanted.joined()) ? 0.5 : 0)
    }

    /// The folders under `roots` whose names match, best first: depth at most
    /// `depth`, for at most `seconds`. Hidden folders, packages and build
    /// folders are skipped, and so is anything the policy refuses.
    public static func walk(
        _ roots: [URL], query: String, depth: Int = 3, seconds: Double = 2, limit: Int = 20, policy: PathPolicy
    ) -> [(url: URL, score: Double)] {
        let skip: Set<String> = ["node_modules", "build", "dist", "DerivedData", "Pods", "venv", "__pycache__", "Library"]
        let deadline = Date().addingTimeInterval(seconds)
        var found: [(URL, Double)] = []
        var seen = Set<String>()
        var queue: [(URL, Int)] = roots.map { ($0, 0) }
        let manager = FileManager.default
        while !queue.isEmpty, Date() < deadline {
            let (folder, level) = queue.removeFirst()
            guard seen.insert(folder.standardizedFileURL.path).inserted else { continue }
            guard let children = try? manager.contentsOfDirectory(
                at: folder, includingPropertiesForKeys: [.isDirectoryKey, .isPackageKey], options: [.skipsHiddenFiles])
            else { continue }
            for child in children {
                let values = try? child.resourceValues(forKeys: [.isDirectoryKey, .isPackageKey])
                guard values?.isDirectory == true, values?.isPackage != true else { continue }
                let name = child.lastPathComponent
                guard !skip.contains(name), policy.allows(child.path) else { continue }
                if let score = score(query: query, name: name) { found.append((child, score)) }
                if level + 1 < depth { queue.append((child, level + 1)) }
            }
        }
        return found.sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.0.path.count < $1.0.path.count }
            .prefix(limit).map { (url: $0.0, score: $0.1) }
    }
}

/// Whether Ira may look inside the folders macOS guards (Documents, Desktop,
/// Downloads). Spotlight leaves them out silently when it may not, and never
/// asks, so the app asks once on purpose and remembers the answer here.
public enum FolderAccess: String, Sendable {
    case granted, denied, notAsked
}

public struct FolderGrants: @unchecked Sendable {
    public static let guarded = ["Documents", "Desktop", "Downloads"]
    public let defaults: UserDefaults
    public let home: URL

    public init(defaults: UserDefaults = .standard, home: URL = FileManager.default.homeDirectoryForCurrentUser) {
        self.defaults = defaults
        self.home = home
    }

    public func access(_ folder: String) -> FolderAccess {
        FolderAccess(rawValue: defaults.string(forKey: "folderAccess.\(folder)") ?? "") ?? .notAsked
    }

    public func record(_ folder: String, _ access: FolderAccess) {
        defaults.set(access.rawValue, forKey: "folderAccess.\(folder)")
    }

    /// Look inside the folder on purpose: macOS asks the person the first time,
    /// and answers at once after that. Blocks until they answer.
    @discardableResult
    public func ask(_ folder: String) -> FolderAccess {
        let url = home.appendingPathComponent(folder)
        let access: FolderAccess = (try? FileManager.default.contentsOfDirectory(atPath: url.path)) != nil ? .granted : .denied
        record(folder, access)
        return access
    }

    /// The guarded folders a search over `scopes` covers but may not look into.
    public func blocked(in scopes: [URL]) -> [String] {
        FolderGrants.guarded.filter { folder in
            let url = home.appendingPathComponent(folder).standardizedFileURL
            let covered = scopes.contains { PathPolicy.isInside(url, $0.standardizedFileURL) || PathPolicy.isInside($0.standardizedFileURL, url) }
            return covered && access(folder) != .granted
        }
    }

    /// The sentence for a search that could not look everywhere.
    public static func notSearched(_ folders: [String]) -> String? {
        guard !folders.isEmpty else { return nil }
        let names = folders.count == 1 ? folders[0] : folders.dropLast().joined(separator: ", ") + " and " + folders.last!
        return "I can't search \(names) yet. Allow Ira for \(folders.count == 1 ? "it" : "them") in Ira's checklist (Settings → Permissions → Files and Folders), then ask again."
    }
}
