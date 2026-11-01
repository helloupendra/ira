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
                    .font(Presence.body)
                    .lineLimit(1...6)
                    .accessibilityIdentifier("drop-text")
                    .listRowBackground(Presence.card)
                HStack(spacing: 8) {
                    Button("Send") {
                        sendingText = true
                        Task {
                            if await drop.send(text: text) { text = "" }
                            sendingText = false
                        }
                    }
                    .buttonStyle(CompactPill(filled: true))
                    .disabled(sendingText || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Spacer()
                    Button("Paste") { if let pasted = UIPasteboard.general.string { text = pasted } }
                        .buttonStyle(CompactPill())
                    Button("Files") { importing = true }
                        .buttonStyle(CompactPill())
                }
                .listRowBackground(Presence.card)
            } header: {
                DotLabel(text: "Send to all your devices")
            } footer: {
                Text("It shows up on all your devices at once, and stays 30 days. You can also share to Ira from any app.")
            }
            if let problem = drop.problem {
                Section { Text(problem).foregroundStyle(Presence.down).listRowBackground(Presence.card) }
            }
            if !drop.sending.isEmpty {
                Section("Sending") {
                    ForEach(drop.sending) { row in
                        HStack {
                            Text(row.name).lineLimit(1)
                            Spacer()
                            if let problem = row.problem {
                                Text(problem).font(.caption).foregroundStyle(Presence.down)
                            } else {
                                ProgressView()
                            }
                        }
                        .listRowBackground(Presence.card)
                    }
                }
            }
            Section {
                if drop.items.isEmpty {
                    Text("Nothing here yet. What you send from any of your devices shows up here.")
                        .font(Presence.secondary)
                        .foregroundStyle(Presence.muted)
                        .listRowBackground(Presence.card)
                }
                ForEach(drop.items) { item in
                    DropRow(item: item).listRowBackground(Presence.card)
                }
                if drop.hasMore {
                    Button("Show older") { Task { await drop.loadOlder() } }
                        .listRowBackground(Presence.card)
                }
            } header: {
                DotLabel(text: "Newest first")
            }
        }
        .listRowSeparatorTint(Presence.line)
        .scrollContentBackground(.hidden)
        .background(Presence.bg)
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
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                DotLabel(text: item.isFile ? "File" : item.link != nil ? "Link" : "Text")
                Spacer()
                Text("From \(item.fromLabel.isEmpty ? "a device" : item.fromLabel)")
                    .font(.system(size: 12))
                    .foregroundStyle(Presence.muted)
            }
            if item.isFile {
                HStack {
                    Text(Drop.safeName(item.name)).font(.system(size: 15, weight: .semibold)).foregroundStyle(Presence.ink).lineLimit(2)
                    Spacer()
                    Text(Drop.size(item.size ?? 0)).font(Presence.mono).foregroundStyle(Presence.muted)
                }
                if let caption = item.text, !caption.isEmpty {
                    Text(caption).font(Presence.secondary).foregroundStyle(Presence.ink).lineLimit(4)
                }
            } else {
                Text(item.text ?? "").font(Presence.body).foregroundStyle(Presence.ink).textSelection(.enabled).lineLimit(12)
            }
            HStack(spacing: 8) {
                if item.isFile {
                    if let saved {
                        ShareLink(item: saved) { Label("Save or open", systemImage: "square.and.arrow.up") }
                            .buttonStyle(CompactPill(filled: true))
                    } else {
                        Button(fetching ? "Getting…" : "Get") {
                            fetching = true
                            Task {
                                saved = await model.drop.save(item)
                                fetching = false
                            }
                        }
                        .buttonStyle(CompactPill(filled: true))
                        .disabled(fetching)
                    }
                } else {
                    Button("Copy") { model.drop.copy(item) }
                        .buttonStyle(CompactPill(filled: true))
                    if let link = item.link {
                        Link("Open", destination: link).buttonStyle(CompactPill())
                    }
                }
            }
            .padding(.top, 2)
        }
        .swipeActions {
            Button("Delete", role: .destructive) { Task { await model.drop.delete(item) } }
        }
    }
}
