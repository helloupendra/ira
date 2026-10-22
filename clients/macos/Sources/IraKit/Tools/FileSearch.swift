import Foundation

/// Finding files with Spotlight (NSMetadataQuery): by name, by what is in them,
/// by kind and by date, inside the folders Ira may use.
public enum FileSearch {
    public static let maxResults = 20

    /// Kinds a person names, as the Uniform Type Identifiers Spotlight files them under.
    public static let kinds: [String: [String]] = [
        "pdf": ["com.adobe.pdf"],
        "word": ["org.openxmlformats.wordprocessingml.document", "com.microsoft.word.doc"],
        "document": [
            "com.adobe.pdf", "org.openxmlformats.wordprocessingml.document", "com.microsoft.word.doc",
            "public.rtf", "com.apple.iwork.pages.sffpages", "com.apple.iwork.pages.pages",
            "org.oasis-open.opendocument.text", "public.plain-text", "net.daringfireball.markdown",
        ],
        "spreadsheet": ["public.spreadsheet"],
        "presentation": ["public.presentation"],
        "image": ["public.image"],
        "video": ["public.movie"],
        "audio": ["public.audio"],
        "text": ["public.text"],
        "folder": ["public.folder"],
        "app": ["com.apple.application"],
        "archive": ["public.archive"],
    ]

    public struct Query: Equatable, Sendable {
        public var words: [String]
        public var kind: String?
        public var modifiedWithinDays: Int?
        public var folder: String?

        public init(text: String?, kind: String?, modifiedWithinDays: Int?, folder: String?) {
            let cleaned = (text ?? "").replacingOccurrences(of: #"[*?"\\]"#, with: " ", options: .regularExpression)
            words = cleaned.split(whereSeparator: \.isWhitespace).prefix(6).map { String($0.prefix(60)) }
            self.kind = kind
            self.modifiedWithinDays = modifiedWithinDays
            self.folder = folder
        }
    }

    /// The Spotlight predicate for a query. Each word must be in the name or the
    /// content; the kind and the date narrow it further.
    public static func predicate(for query: Query, now: Date = Date()) -> NSPredicate {
        var parts: [NSPredicate] = []
        for word in query.words {
            parts.append(any([
                NSPredicate(format: "%K LIKE[cd] %@", "kMDItemFSName", "*\(word)*"),
                NSPredicate(format: "%K CONTAINS[cd] %@", "kMDItemTextContent", word),
            ]))
        }
        if let kind = query.kind, let types = kinds[kind] {
            parts.append(any(types.map { NSPredicate(format: "%K == %@", "kMDItemContentTypeTree", $0) }))
        }
        if let days = query.modifiedWithinDays {
            let since = now.addingTimeInterval(-Double(days) * 86_400) as NSDate
            parts.append(any([
                NSPredicate(format: "%K >= %@", "kMDItemFSContentChangeDate", since),
                NSPredicate(format: "%K >= %@", "kMDItemDateAdded", since),
            ]))
        }
        if parts.isEmpty {
            // Nothing to narrow by: recent files, newest first, rather than everything.
            let since = now.addingTimeInterval(-7 * 86_400) as NSDate
            parts.append(NSPredicate(format: "%K >= %@", "kMDItemFSContentChangeDate", since))
        }
        return all(parts)
    }

    // NSMetadataQuery throws on an AND or OR of a single predicate: use the predicate itself.
    static func all(_ parts: [NSPredicate]) -> NSPredicate {
        parts.count == 1 ? parts[0] : NSCompoundPredicate(andPredicateWithSubpredicates: parts)
    }

    static func any(_ parts: [NSPredicate]) -> NSPredicate {
        parts.count == 1 ? parts[0] : NSCompoundPredicate(orPredicateWithSubpredicates: parts)
    }

    /// The folder a person named ("Downloads", "~/Projects", "/Volumes/Work") as a path.
    public static func folderPath(_ folder: String, home: URL) -> String {
        let trimmed = folder.trimmingCharacters(in: .whitespacesAndNewlines)
        let known = ["desktop", "documents", "downloads", "pictures", "movies", "music", "public"]
        if known.contains(trimmed.lowercased()) {
            return home.appendingPathComponent(trimmed.prefix(1).uppercased() + trimmed.dropFirst().lowercased()).path
        }
        if trimmed.hasPrefix("~") || trimmed.hasPrefix("/") { return trimmed }
        return home.appendingPathComponent(trimmed).path
    }

    public struct Found: Equatable, Sendable {
        public let url: URL
        public let kind: String?
        public let size: Int?
        public let modified: Date?
    }

    /// Run the query in Spotlight on the main thread, where NSMetadataQuery needs a
    /// run loop; at most `limit` files the policy allows, newest first.
    @MainActor
    public static func run(
        _ predicate: NSPredicate, scopes: [URL], policy: PathPolicy, limit: Int = maxResults,
        timeout: TimeInterval = 8
    ) async -> [Found] {
        let query = NSMetadataQuery()
        query.predicate = predicate
        query.searchScopes = scopes
        query.sortDescriptors = [NSSortDescriptor(key: "kMDItemFSContentChangeDate", ascending: false)]
        return await withCheckedContinuation { (continuation: CheckedContinuation<[Found], Never>) in
            var finished = false
            var observer: NSObjectProtocol?
            func finish() {
                guard !finished else { return }
                finished = true
                query.disableUpdates()
                query.stop()
                if let observer { NotificationCenter.default.removeObserver(observer) }
                var found: [Found] = []
                for index in 0..<query.resultCount {
                    guard found.count < limit,
                        let item = query.result(at: index) as? NSMetadataItem,
                        let path = item.value(forAttribute: NSMetadataItemPathKey) as? String,
                        policy.allows(path)
                    else { continue }
                    found.append(Found(
                        url: URL(fileURLWithPath: path),
                        kind: item.value(forAttribute: "kMDItemKind") as? String,
                        size: (item.value(forAttribute: NSMetadataItemFSSizeKey) as? NSNumber)?.intValue,
                        modified: item.value(forAttribute: NSMetadataItemFSContentChangeDateKey) as? Date))
                }
                continuation.resume(returning: found)
            }
            observer = NotificationCenter.default.addObserver(
                forName: .NSMetadataQueryDidFinishGathering, object: query, queue: .main
            ) { _ in MainActor.assumeIsolated { finish() } }
            if !query.start() {
                finish()
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { finish() }
        }
    }
}
