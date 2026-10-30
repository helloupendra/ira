import IraPhoneKit
import Observation
import SwiftUI
import UIKit
import UserNotifications

/// The person's Drop on this iPhone: the newest items, kept current by the device connection's
/// `drop` frames while Ira is on screen, and caught up when it connects again. Text from another
/// device comes as a notification with Copy while the Drop screen is not the one in front.
@MainActor
@Observable
final class DropBox {
    struct Sending: Identifiable {
        let id = UUID()
        let name: String
        var problem: String?
    }

    private(set) var items: [DropItem] = []
    private(set) var hasMore = false
    private(set) var sending: [Sending] = []
    /// What went wrong last, in plain words.
    var problem: String?
    /// The Drop screen is open: new items show there, not as notifications.
    var visible = false
    @ObservationIgnored private var loaded = false

    private var client: DropClient? { AppModel.shared.dropClient() }

    /// Where a file from Drop is kept until it is saved or opened elsewhere.
    static var folder: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("Drop", isDirectory: true)
    }

    // MARK: Keeping current

    func refresh() async {
        guard let client else { return }
        do {
            let page = try await client.list()
            items = page.items
            hasMore = page.hasMore
            loaded = true
            problem = nil
        } catch {
            problem = error.localizedDescription
        }
    }

    func loadOlder() async {
        guard let client, let oldest = items.last?.id else { return }
        do {
            let page = try await client.list(before: oldest)
            merge(page.items)
            hasMore = page.hasMore
        } catch {
            problem = error.localizedDescription
        }
    }

    /// The connection is back: what arrived meanwhile, quietly (no notification for each).
    func catchUp() async {
        guard loaded, let newest = items.first?.id, let client else { return }
        if let page = try? await client.list(after: newest) { merge(page.items) }
    }

    func handle(_ frame: DropFrame) {
        switch frame {
        case .new(let item):
            merge([item])
            if !visible && item.fromDeviceID != AppModel.shared.settings.deviceID { DropNotes.shared.post(item) }
        case .deleted(let id):
            items.removeAll { $0.id == id }
        }
    }

    private func merge(_ more: [DropItem]) {
        var seen = Set<Int>()
        items = (more + items).filter { seen.insert($0.id).inserted }.sorted { $0.id > $1.id }
    }

    // MARK: Sending

    func send(text: String) async -> Bool {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let client else { return false }
        do {
            merge([try await client.send(text: text)])
            problem = nil
            return true
        } catch {
            problem = error.localizedDescription
            return false
        }
    }

    /// Files picked in Files: each read while its access lasts, one after another.
    func send(files: [URL]) async {
        guard let client else { return }
        for file in files {
            let row = Sending(name: file.lastPathComponent)
            sending.append(row)
            let open = file.startAccessingSecurityScopedResource()
            defer { if open { file.stopAccessingSecurityScopedResource() } }
            do {
                merge([try await client.send(file: file)])
                sending.removeAll { $0.id == row.id }
            } catch {
                if let index = sending.firstIndex(where: { $0.id == row.id }) {
                    sending[index].problem = error.localizedDescription
                }
            }
        }
    }

    func clearFailed() {
        sending.removeAll { $0.problem != nil }
    }

    // MARK: Using an item

    func copy(_ item: DropItem) {
        if let text = item.text { UIPasteboard.general.string = text }
    }

    /// A file, fetched and checked, ready to save or open with the share sheet.
    func save(_ item: DropItem) async -> URL? {
        guard let client else { return nil }
        do {
            return try await client.save(item, into: DropBox.folder)
        } catch {
            problem = error.localizedDescription
            return nil
        }
    }

    func delete(_ item: DropItem) async {
        guard let client else { return }
        do {
            try await client.delete(item.id)
            items.removeAll { $0.id == item.id }
        } catch {
            problem = error.localizedDescription
        }
    }
}

/// Drop's notification: something new from another device, with Copy for text and links.
@MainActor
final class DropNotes: NSObject, UNUserNotificationCenterDelegate {
    static let shared = DropNotes()
    private static let category = "drop.text"

    func install() {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: DropNotes.category, actions: [UNNotificationAction(identifier: "copy", title: "Copy")],
                intentIdentifiers: [])
        ])
    }

    func post(_ item: DropItem) {
        let from = item.fromLabel.isEmpty ? "a device" : item.fromLabel
        let title = "In your Drop, from \(from)"
        let body = item.preview
        let copy = item.isFile ? nil : item.text
        let id = "drop-\(item.id)"
        Task {
            let center = UNUserNotificationCenter.current()
            guard (try? await center.requestAuthorization(options: [.alert, .sound])) == true else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            if let copy {
                content.categoryIdentifier = DropNotes.category
                content.userInfo = ["copy": copy]
            }
            try? await center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        guard response.actionIdentifier == "copy",
            let text = response.notification.request.content.userInfo["copy"] as? String
        else { return }
        await MainActor.run { UIPasteboard.general.string = text }
    }

    /// Shown even while Ira is in front (on another screen than Drop).
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}
