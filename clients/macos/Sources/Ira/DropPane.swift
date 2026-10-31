import AppKit
import IraKit
import SwiftUI
import UniformTypeIdentifiers

/// The pane's own state: a drag over it, and an item waiting for "Delete from all devices?".
final class DropPaneState: ObservableObject {
    @Published var targeted = false
    @Published var deleting: DropItem?
}

/// Drop in the window: every item, newest first, with what can be done with it; files and
/// text dragged onto it are sent to the person's other devices. A file arriving here is
/// never saved until Save is chosen.
struct DropPane: View {
    @ObservedObject var drop: DropBox
    @StateObject private var state = DropPaneState()

    var body: some View {
        Group {
            if drop.items.isEmpty {
                empty
            } else {
                list
            }
        }
        .overlay {
            if state.targeted {
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(Color.iraText, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                    .background(Color.iraText.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
                    .overlay(Label("Drop to send to your devices", systemImage: "tray.and.arrow.down").font(.headline))
                    .padding(10)
                    .allowsHitTesting(false)
            }
        }
        .onDrop(of: [.fileURL, .url, .plainText], isTargeted: $state.targeted) { providers in
            DropPane.receive(providers, into: drop)
            return true
        }
        .navigationTitle("Drop")
        .navigationSubtitle("Shared by your devices for 30 days")
        .toolbar {
            ToolbarItem {
                Button {
                    Task { await drop.sendClipboard() }
                } label: {
                    Label("Send Clipboard", systemImage: "doc.on.clipboard")
                }
                .help("Send what you copied to your devices (⌃⌥⌘V)")
            }
            ToolbarItem {
                Button(action: chooseFiles) {
                    Label("Send Files…", systemImage: "paperclip")
                }
                .help("Send files to your devices")
            }
            ToolbarItem {
                Button(action: openFolder) {
                    Label("Open Downloads/Ira", systemImage: "folder")
                }
                .help("Open Downloads/Ira, where saved files go")
            }
        }
        .confirmationDialog(
            "Delete from all your devices?", isPresented: Binding(get: { state.deleting != nil }, set: { if !$0 { state.deleting = nil } }),
            presenting: state.deleting
        ) { item in
            Button("Delete", role: .destructive) { Task { await drop.delete(item) } }
        } message: { item in
            Text(DropList.title(item))
        }
        .task { await drop.refresh() }
    }

    private var empty: some View {
        ContentUnavailableView {
            Label("Your Drop is empty", systemImage: "tray")
        } description: {
            Text("Drag files or text here to send them to your other devices, or send what you copied. What your other devices send shows here.")
        } actions: {
            Button("Send Clipboard") { Task { await drop.sendClipboard() } }
            Button("Send Files…", action: chooseFiles)
        }
    }

    private var list: some View {
        List {
            ForEach(DropList.sections(drop.items)) { section in
                Section(section.title) {
                    ForEach(section.items) { item in
                        DropRow(item: item, saved: drop.savedFile(item) != nil, drop: drop, delete: { state.deleting = item })
                    }
                }
            }
            if drop.hasMore {
                Button("Show older items") { Task { await drop.loadOlder() } }
                    .buttonStyle(.link)
                    .padding(.vertical, 6)
            }
        }
        .listStyle(.inset)
    }

    private func chooseFiles() {
        let picker = NSOpenPanel()
        picker.canChooseFiles = true
        picker.canChooseDirectories = false
        picker.allowsMultipleSelection = true
        picker.prompt = "Send to Drop"
        guard picker.runModal() == .OK else { return }
        let files = picker.urls
        Task { await drop.send(files: files) }
    }

    private func openFolder() {
        try? FileManager.default.createDirectory(at: DropBox.folder, withIntermediateDirectories: true)
        NSWorkspace.shared.open(DropBox.folder)
    }

    /// What was dragged in: files, else a link or text.
    static func receive(_ providers: [NSItemProvider], into drop: DropBox) {
        for provider in providers {
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.fileURL.identifier) { data, _ in
                    guard let data, let url = URL(dataRepresentation: data, relativeTo: nil), url.isFileURL else { return }
                    Task { @MainActor in await drop.send(files: [url]) }
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.url.identifier) { data, _ in
                    guard let data, let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
                    Task { @MainActor in await drop.send(text: url.absoluteString) }
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.utf8PlainText.identifier) { data, _ in
                    guard let data, let text = String(data: data, encoding: .utf8) else { return }
                    Task { @MainActor in await drop.send(text: text) }
                }
            }
        }
    }
}

/// One item: its kind, what it is, where it came from, and its actions.
struct DropRow: View {
    let item: DropItem
    let saved: Bool
    let drop: DropBox
    let delete: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: DropList.symbol(item))
                .font(.title3)
                .foregroundStyle(Color.iraText)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(DropList.title(item))
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                Text(DropList.detail(item))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 12)
            HStack(spacing: 4) {
                if item.isFile {
                    action(saved ? "Saved" : "Save", icon: saved ? "checkmark.circle" : "arrow.down.circle",
                           help: "Save to Downloads/Ira") { Task { _ = try? await drop.save(item) } }
                        .disabled(saved)
                    action("Show in Finder", icon: "magnifyingglass", help: saved ? "Show in Finder" : "Save it first") { drop.reveal(item) }
                        .disabled(!saved)
                } else {
                    action("Copy", icon: "doc.on.doc", help: "Copy") { Task { await drop.copy(item) } }
                    if item.link != nil {
                        action("Open", icon: "arrow.up.right.square", help: "Open the link") { Task { await drop.open(item) } }
                    } else {
                        action("", icon: "arrow.up.right.square", help: "") {}.hidden()  // keeps the columns lined up
                    }
                }
                action("Delete", icon: "trash", help: "Delete from all your devices", run: delete)
            }
        }
        .padding(.vertical, 4)
        .contextMenu {
            if item.isFile {
                Button("Save to Downloads/Ira") { Task { _ = try? await drop.save(item) } }.disabled(saved)
                Button("Show in Finder") { drop.reveal(item) }.disabled(!saved)
            } else {
                Button("Copy") { Task { await drop.copy(item) } }
                if item.link != nil { Button("Open Link") { Task { await drop.open(item) } } }
            }
            Divider()
            Button("Delete from All Devices…", role: .destructive, action: delete)
        }
    }

    private func action(_ title: String, icon: String, help: String, run: @escaping () -> Void) -> some View {
        Button(action: run) {
            Image(systemName: icon)
                .frame(width: 22, height: 22)
        }
        .buttonStyle(.borderless)
        .help(help)
        .accessibilityLabel(title)
    }
}
