import IraPhoneKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Share → Ira Drop from any app. What was shared is shown first, and goes to the person's Drop
/// only on Send to Drop: any app can open a share sheet, so nothing is sent without that tap.
/// It reads this iPhone's key and its Ira's address from the Keychain group the app shares
/// with it.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        model.done = { [weak self] in self?.extensionContext?.completeRequest(returningItems: nil) }
        model.cancelled = { [weak self] in
            self?.extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
        }
        let host = UIHostingController(rootView: ShareSheet(model: model))
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        model.collect((extensionContext?.inputItems as? [NSExtensionItem]) ?? [])
    }
}

/// What came in, and sending it. On the main actor: the sheet reads it, and the item
/// providers' callbacks only fill a `Found`, which is handed over on the main queue.
@MainActor
final class ShareModel: ObservableObject {
    enum Phase: Equatable {
        case reading, ready, sending, sent
        case failed(String)
    }

    @Published var phase: Phase = .reading
    @Published var text = ""
    @Published var files: [URL] = []
    var done: () -> Void = {}
    var cancelled: () -> Void = {}

    /// Copies of the shared files, readable after the share sheet's own access ends.
    nonisolated private static let folder = FileManager.default.temporaryDirectory.appendingPathComponent("IraShare", isDirectory: true)

    /// This iPhone's pairing, as the app keeps it in the shared Keychain group.
    static func client() -> DropClient? {
        let store = KeychainStore(accessGroup: KeychainStore.sharedGroup)
        guard let server = store.load(SecretAccount.server), store.load(SecretAccount.device) != nil else { return nil }
        return DropClient(server: server, token: { store.load(SecretAccount.device) })
    }

    func collect(_ items: [NSExtensionItem]) {
        let folder = Self.folder
        try? FileManager.default.removeItem(at: folder)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let group = DispatchGroup()
        let found = Found()
        for provider in items.flatMap({ $0.attachments ?? [] }) {
            group.enter()
            if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                !provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier)
            {
                provider.loadItem(forTypeIdentifier: UTType.url.identifier) { item, _ in
                    if let url = item as? URL { found.add(word: url.absoluteString) }
                    group.leave()
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) { item, _ in
                    if let text = item as? String { found.add(word: text) }
                    group.leave()
                }
            } else {
                let type = provider.registeredTypeIdentifiers.first ?? UTType.data.identifier
                provider.loadFileRepresentation(forTypeIdentifier: type) { url, _ in
                    // The file is readable only inside this handler: keep a copy.
                    if let url { found.keep(url, in: folder) }
                    group.leave()
                }
            }
        }
        group.notify(queue: .main) {
            MainActor.assumeIsolated { self.show(found.all) }
        }
    }

    private func show(_ all: (words: [String], copies: [URL])) {
        text = all.words.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        files = all.copies
        if Self.client() == nil {
            phase = .failed("Open Ira and pair this iPhone first.")
        } else if text.isEmpty && files.isEmpty {
            phase = .failed("Nothing came with this share.")
        } else {
            phase = .ready
        }
    }

    func send() {
        guard phase == .ready, let client = Self.client() else { return }
        phase = .sending
        let text = self.text
        let files = self.files
        Task {
            do {
                if files.isEmpty {
                    _ = try await client.send(text: text)
                } else {
                    for (index, file) in files.enumerated() {
                        _ = try await client.send(file: file, caption: index == 0 && !text.isEmpty ? text : nil)
                    }
                }
                self.phase = .sent
                try? await Task.sleep(nanoseconds: 1_200_000_000)
                self.done()
            } catch {
                self.phase = .failed(error.localizedDescription)
            }
        }
    }
}

/// What the share's items held, gathered from callbacks that come on any thread.
private final class Found: @unchecked Sendable {
    private let lock = NSLock()
    private var words: [String] = []
    private var copies: [URL] = []

    var all: (words: [String], copies: [URL]) { lock.withLock { (words, copies) } }

    func add(word: String) {
        lock.withLock { words.append(word) }
    }

    /// A copy of a shared file in [folder], never over another one.
    func keep(_ file: URL, in folder: URL) {
        lock.withLock {
            let target = Drop.freeURL(in: folder, name: Drop.safeName(file.lastPathComponent))
            if (try? FileManager.default.copyItem(at: file, to: target)) != nil { copies.append(target) }
        }
    }
}

struct ShareSheet: View {
    @ObservedObject var model: ShareModel

    var body: some View {
        NavigationStack {
            Form {
                if model.phase == .reading {
                    ProgressView("Reading what you shared…")
                } else {
                    if !model.text.isEmpty {
                        Section("Text") { Text(model.text).lineLimit(8) }
                    }
                    if !model.files.isEmpty {
                        Section("Files") {
                            ForEach(model.files, id: \.self) { file in
                                HStack {
                                    Text(file.lastPathComponent).lineLimit(1)
                                    Spacer()
                                    Text(Drop.size(Self.size(of: file))).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    Section {
                        switch model.phase {
                        case .sending: ProgressView("Sending…")
                        case .sent: Label("Sent. It is on your other devices now.", systemImage: "checkmark.circle")
                        case .failed(let why): Text(why).foregroundStyle(.red)
                        default: Text("It goes to all your devices once you send it, and stays 30 days.")
                            .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Send to your Drop?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.phase == .sent ? "Close" : "Cancel") {
                        if model.phase == .sent { model.done() } else { model.cancelled() }
                    }
                    .disabled(model.phase == .sending)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send to Drop") { model.send() }.disabled(model.phase != .ready)
                }
            }
        }
    }

    static func size(of file: URL) -> Int {
        (try? FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int) ?? 0
    }
}
