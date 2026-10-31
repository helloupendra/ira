import AppKit
import Foundation
import IraKit
import UserNotifications

/// The person's Drop on this Mac: the newest items for the menu, kept current by the device
/// connection's `drop` frames. Text from another device comes as a notification with Copy;
/// a file as one with Save, and only Save writes it to ~/Downloads/Ira (then Show in Finder).
@MainActor
final class DropBox: NSObject, ObservableObject {
    @Published private(set) var items: [DropItem] = []
    /// Older items wait on the server: the window offers to show them.
    @Published private(set) var hasMore = false
    /// Where each file saved on this Mac went, for Show in Finder.
    @Published private(set) var saved: [Int: URL] = [:]

    private let settings: AppSettings
    private let secrets: SecretStore
    private var loaded = false

    init(settings: AppSettings, secrets: SecretStore) {
        self.settings = settings
        self.secrets = secrets
        super.init()
        DropNotes.shared.install()
        DropNotes.shared.onSave = { [weak self] id in
            Task { await self?.saveArrived(id) }
        }
    }

    /// ~/Downloads/Ira, where files from Drop go.
    static var folder: URL {
        let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads")
        return downloads.appendingPathComponent("Ira", isDirectory: true)
    }

    private var client: DropClient? {
        let secrets = self.secrets
        guard !settings.server.isEmpty, secrets.load(SecretAccount.device) != nil else { return nil }
        return DropClient(server: settings.server, token: { secrets.load(SecretAccount.device) })
    }

    // MARK: Keeping current

    func refresh() async {
        guard let client else { return }
        do {
            let page = try await client.list(limit: 50)
            items = page.items
            hasMore = page.hasMore
            loaded = true
        } catch {
            IraLog.shared.warning("drop: the list did not load (\(type(of: error)))")
        }
    }

    /// The connection is back: what arrived meanwhile, quietly (no notification for each).
    func catchUp() async {
        guard loaded, let newest = items.first?.id, let client else { return await refresh() }
        if let page = try? await client.list(after: newest) { merge(page.items) }
    }

    func handle(_ frame: DropFrame) {
        switch frame {
        case .new(let item):
            merge([item])
            if item.fromDeviceID != settings.deviceID { arrived(item) }
        case .deleted(let id):
            items.removeAll { $0.id == id }
        }
    }

    /// The next older page, for the window's list.
    func loadOlder() async {
        guard let client, let oldest = items.last?.id else { return }
        if let page = try? await client.list(before: oldest, limit: 50) {
            merge(page.items)
            hasMore = page.hasMore
        }
    }

    private func merge(_ more: [DropItem]) {
        var seen = Set<Int>()
        items = (more + items).filter { seen.insert($0.id).inserted }.sorted { $0.id > $1.id }
        if items.count > 500 { items.removeLast(items.count - 500) }
    }

    private func arrived(_ item: DropItem) {
        let from = item.fromLabel.isEmpty ? "a device" : item.fromLabel
        switch DropArrival(item) {
        case .copy(let text):
            DropNotes.shared.post(title: "In your Drop, from \(from)", body: item.preview, copy: text)
        case .offerSave(let id):
            DropNotes.shared.post(title: "In your Drop, from \(from)", body: item.preview, save: id)
        }
    }

    /// Save on a file's notification: only now is it written to ~/Downloads/Ira.
    private func saveArrived(_ id: Int) async {
        if !items.contains(where: { $0.id == id }) { await refresh() }
        guard let item = items.first(where: { $0.id == id && $0.isFile }) else {
            return DropNotes.shared.post(title: "Not saved", body: "That file is no longer in your Drop.")
        }
        do {
            let saved = try await save(item)
            DropNotes.shared.post(title: "Saved to Downloads/Ira", body: item.preview, reveal: saved)
        } catch {
            DropNotes.shared.post(title: "Not saved", body: "\(item.preview): \(error.localizedDescription)")
        }
    }

    // MARK: Sending

    func send(text: String) async {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard let client else { return DropNotes.shared.post(title: "Not sent", body: "This Mac is not paired with an Ira.") }
        do {
            merge([try await client.send(text: text)])
            DropNotes.shared.post(title: "Sent to your Drop", body: String(text.prefix(200)))
        } catch {
            DropNotes.shared.post(title: "Not sent", body: error.localizedDescription)
        }
    }

    func send(files: [URL]) async {
        guard let client else { return DropNotes.shared.post(title: "Not sent", body: "This Mac is not paired with an Ira.") }
        var sent: [String] = []
        for file in files where !file.hasDirectoryPath {
            do {
                merge([try await client.send(file: file)])
                sent.append(file.lastPathComponent)
            } catch {
                DropNotes.shared.post(title: "\(file.lastPathComponent) was not sent", body: error.localizedDescription)
            }
        }
        if !sent.isEmpty {
            DropNotes.shared.post(title: "Sent to your Drop", body: sent.joined(separator: ", "))
        }
    }

    /// The clipboard: files copied in the Finder, else its text.
    func sendClipboard() async {
        let board = NSPasteboard.general
        let files = (board.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        if !files.isEmpty { return await send(files: files) }
        if let text = board.string(forType: .string), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return await send(text: text)
        }
        DropNotes.shared.post(title: "Nothing to send", body: "The clipboard is empty.")
    }

    // MARK: Using an item

    /// Text or a link onto the clipboard; a file, saved first, as the file.
    func copy(_ item: DropItem) async {
        let board = NSPasteboard.general
        if item.isFile {
            guard let saved = try? await save(item) else { return }
            board.clearContents()
            board.writeObjects([saved as NSURL])
        } else if let text = item.text {
            board.clearContents()
            board.setString(text, forType: .string)
        }
    }

    func copyLatest() async {
        await refreshIfEmpty()
        guard let latest = items.first else {
            return DropNotes.shared.post(title: "Nothing to copy", body: "Your Drop is empty.")
        }
        await copy(latest)
        DropNotes.shared.post(title: "Copied from your Drop", body: latest.preview)
    }

    private func refreshIfEmpty() async {
        if items.isEmpty { await refresh() }
    }

    @discardableResult
    func save(_ item: DropItem) async throws -> URL {
        guard let client else { throw DropClient.Failure("this Mac is not paired") }
        let saved = try await client.save(item, into: DropBox.folder)
        self.saved[item.id] = saved
        IraLog.shared.info("drop: saved a file")
        return saved
    }

    /// Where this file was saved on this Mac, if it still is there.
    func savedFile(_ item: DropItem) -> URL? {
        guard let url = saved[item.id], FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    /// Show a saved file in the Finder.
    func reveal(_ item: DropItem) {
        if let url = savedFile(item) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
    }

    func open(_ item: DropItem) async {
        if let link = item.link {
            NSWorkspace.shared.open(link)
        } else if item.isFile, let saved = try? await save(item) {
            NSWorkspace.shared.activateFileViewerSelecting([saved])
        }
    }

    func delete(_ item: DropItem) async {
        guard let client else { return }
        do {
            try await client.delete(item.id)
            items.removeAll { $0.id == item.id }
            saved[item.id] = nil
        } catch {
            DropNotes.shared.post(title: "Not deleted", body: error.localizedDescription)
        }
    }
}

/// Drop's notifications: Copy on text and links, Save on a file that arrived, Show in Finder
/// once it is saved.
@MainActor
final class DropNotes: NSObject, UNUserNotificationCenterDelegate {
    static let shared = DropNotes()
    private static let copyCategory = "drop.text"
    private static let saveCategory = "drop.offer"
    private static let fileCategory = "drop.file"
    private var installed = false
    /// Save was chosen on a file's notification: the item's id.
    var onSave: ((Int) -> Void)?

    /// Notification Center needs an app bundle: a bare `swift run` has none.
    private var available: Bool { Bundle.main.bundleIdentifier != nil }

    func install() {
        guard available, !installed else { return }
        installed = true
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: DropNotes.copyCategory, actions: [UNNotificationAction(identifier: "copy", title: "Copy")],
                intentIdentifiers: []),
            UNNotificationCategory(
                identifier: DropNotes.saveCategory, actions: [UNNotificationAction(identifier: "save", title: "Save")],
                intentIdentifiers: []),
            UNNotificationCategory(
                identifier: DropNotes.fileCategory,
                actions: [UNNotificationAction(identifier: "reveal", title: "Show in Finder")], intentIdentifiers: []),
        ])
    }

    func post(title: String, body: String, copy: String? = nil, save: Int? = nil, reveal: URL? = nil) {
        guard available else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body.count > 240 ? String(body.prefix(239)) + "…" : body
            if let copy {
                content.categoryIdentifier = DropNotes.copyCategory
                content.userInfo = ["copy": copy]
            } else if let save {
                content.categoryIdentifier = DropNotes.saveCategory
                content.userInfo = ["save": save]
            } else if let reveal {
                content.categoryIdentifier = DropNotes.fileCategory
                content.userInfo = ["reveal": reveal.path]
            }
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let info = response.notification.request.content.userInfo
        let action = response.actionIdentifier
        let copy = info["copy"] as? String
        let save = info["save"] as? Int
        let reveal = info["reveal"] as? String
        DispatchQueue.main.async {
            if let copy, action == "copy" || action == UNNotificationDefaultActionIdentifier {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(copy, forType: .string)
            } else if let save {
                // Save, or a click on the notification itself: the person chose it either way.
                if action == "save" || action == UNNotificationDefaultActionIdentifier {
                    MainActor.assumeIsolated { DropNotes.shared.onSave?(save) }
                }
            } else if let reveal {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: reveal)])
            }
            completionHandler()
        }
    }

    /// Shown even while Ira is the app in front.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}

/// Files and text dragged onto Ira's menu-bar icon go to Drop. The status item's window
/// passes the drag to its delegate, so the icon itself stays an ordinary button.
@MainActor
final class DropTarget: NSObject, NSWindowDelegate, NSDraggingDestination {
    private let drop: DropBox
    private let button: NSStatusBarButton

    init(drop: DropBox, button: NSStatusBarButton) {
        self.drop = drop
        self.button = button
        super.init()
        guard let window = button.window else { return }
        window.registerForDraggedTypes([.fileURL, .URL, .string])
        window.delegate = self
    }

    func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        button.highlight(true)
        return .copy
    }

    func draggingExited(_ sender: NSDraggingInfo?) {
        button.highlight(false)
    }

    func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        button.highlight(false)
        let board = sender.draggingPasteboard
        let files = (board.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        if !files.isEmpty {
            Task { await drop.send(files: files) }
            return true
        }
        let link = (board.readObjects(forClasses: [NSURL.self], options: nil) as? [URL])?.first?.absoluteString
        if let text = link ?? board.string(forType: .string), !text.isEmpty {
            Task { await drop.send(text: text) }
            return true
        }
        return false
    }
}
