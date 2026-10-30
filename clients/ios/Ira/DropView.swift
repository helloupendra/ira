import IraPhoneKit
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Drop: send text, a link or files to all your devices, and see what arrived from them,
/// newest first. Text and links have Copy first; a file is fetched, then saved or opened
/// with the share sheet.
struct DropView: View {
    @Environment(AppModel.self) private var model
    @State private var text = ""
    @State private var sendingText = false
    @State private var importing = false

    private var drop: DropBox { model.drop }

    var body: some View {
        List {
            Section {
                TextField("Text or a link", text: $text, axis: .vertical)
                    .lineLimit(1...6)
                    .accessibilityIdentifier("drop-text")
                HStack {
                    Button("Send") {
                        sendingText = true
                        Task {
                            if await drop.send(text: text) { text = "" }
                            sendingText = false
                        }
                    }
                    .disabled(sendingText || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Spacer()
                    Button("Paste") { if let pasted = UIPasteboard.general.string { text = pasted } }
                    Button("Files") { importing = true }
                }
                .buttonStyle(.borderless)
            } footer: {
                Text("It shows up on all your devices at once, and stays 30 days. You can also share to Ira from any app.")
            }
            if let problem = drop.problem {
                Section { Text(problem).foregroundStyle(.red) }
            }
            if !drop.sending.isEmpty {
                Section("Sending") {
                    ForEach(drop.sending) { row in
                        HStack {
                            Text(row.name).lineLimit(1)
                            Spacer()
                            if let problem = row.problem {
                                Text(problem).font(.caption).foregroundStyle(.red)
                            } else {
                                ProgressView()
                            }
                        }
                    }
                }
            }
            Section {
                if drop.items.isEmpty {
                    Text("Nothing here yet. What you send from any of your devices shows up here.")
                        .foregroundStyle(.secondary)
                }
                ForEach(drop.items) { item in DropRow(item: item) }
                if drop.hasMore {
                    Button("Show older") { Task { await drop.loadOlder() } }
                }
            }
        }
        .navigationTitle("Drop")
        .fileImporter(isPresented: $importing, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
            if case .success(let files) = result { Task { await drop.send(files: files) } }
        }
        .refreshable { await drop.refresh() }
        .task { await drop.refresh() }
        .onAppear { drop.visible = true }
        .onDisappear {
            drop.visible = false
            drop.clearFailed()
        }
    }
}

private struct DropRow: View {
    let item: DropItem
    @Environment(AppModel.self) private var model
    @State private var saved: URL?
    @State private var fetching = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if item.isFile {
                HStack {
                    Text(Drop.safeName(item.name)).bold().lineLimit(2)
                    Spacer()
                    Text(Drop.size(item.size ?? 0)).font(.caption).foregroundStyle(.secondary)
                }
                if let caption = item.text, !caption.isEmpty { Text(caption).lineLimit(4) }
            } else {
                Text(item.text ?? "").textSelection(.enabled).lineLimit(12)
            }
            Text("From \(item.fromLabel.isEmpty ? "a device" : item.fromLabel)")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 16) {
                if item.isFile {
                    if let saved {
                        ShareLink(item: saved) { Label("Save or open", systemImage: "square.and.arrow.up") }
                    } else {
                        Button(fetching ? "Getting…" : "Get") {
                            fetching = true
                            Task {
                                saved = await model.drop.save(item)
                                fetching = false
                            }
                        }
                        .disabled(fetching)
                    }
                } else {
                    Button("Copy") { model.drop.copy(item) }
                    if let link = item.link { Link("Open", destination: link) }
                }
            }
            .buttonStyle(.borderless)
        }
        .swipeActions {
            Button("Delete", role: .destructive) { Task { await model.drop.delete(item) } }
        }
    }
}
