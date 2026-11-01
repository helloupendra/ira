import IraPhoneKit
import SwiftUI

/// "Get Ira ready": pair, the microphone, speech recognition, then each skill,
/// each with one line on why, and the button that does it.
struct SetupView: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = false

    var body: some View {
        ScrollView {
            SetupContent(
                rows: model.rows, notice: model.notice,
                act: { act(on: $0) })
        }
        .background(Presence.bg.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) {
            Button {
                model.finishSetup()
            } label: {
                Text(model.ready ? "Start talking to \(model.assistantName)" : "Pair and allow the microphone first")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(model.ready ? Color.white : Presence.muted)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 15)
                    .background(Capsule().fill(model.ready ? Presence.greenDeep : Presence.card))
                    .overlay(Capsule().strokeBorder(model.ready ? Color.clear : Presence.line, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .disabled(!model.ready)
            .accessibilityIdentifier("start")
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(Presence.bg.opacity(0.96))
        }
        .navigationTitle("Get Ira ready")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Presence.bg, for: .navigationBar)
        .sheet(isPresented: $pairing) { PairView() }
    }

    private func act(on row: ChecklistRow) {
        switch row.action {
        case .pair: pairing = true
        case .allow: Task { await model.allow(row.item) }
        case .openSettings: model.openSettings()
        case .done, .unavailable: break
        }
    }
}

/// The page itself, from plain values: the lens and a line on what this is, then the
/// checklist in one card.
struct SetupContent: View {
    let rows: [ChecklistRow]
    var notice: String?
    var act: (ChecklistRow) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 14) {
                Lens(size: 52, breathing: true)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Get Ira ready").font(Presence.serif(26)).foregroundStyle(Presence.ink)
                    Text("Once. Only Pair and Microphone are needed to talk.")
                        .font(Presence.secondary)
                        .foregroundStyle(Presence.muted)
                }
            }
            .padding(.top, 8)
            if let notice {
                Text(notice)
                    .font(Presence.secondary)
                    .foregroundStyle(Presence.ink)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Presence.warn.opacity(0.08)))
                    .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Presence.warn.opacity(0.45), lineWidth: 1))
                    .accessibilityIdentifier("notice")
            }
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if index > 0 {
                        Rectangle().fill(Presence.line).frame(height: 1).padding(.leading, 54)
                    }
                    ChecklistRowView(row: row) { act(row) }
                }
            }
            .background(RoundedRectangle(cornerRadius: 18).fill(Presence.card))
            .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Presence.line, lineWidth: 1))
            Text("You can allow the rest later: Settings, Get Ira ready. iOS lets no app read your calls, SMS or other apps' notifications, so Ira for iPhone never asks for them.")
                .font(.system(size: 12))
                .foregroundStyle(Presence.muted)
                .padding(.horizontal, 4)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 20)
    }
}

struct ChecklistRowView: View {
    let row: ChecklistRow
    let act: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(color)
                .frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(row.title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Presence.ink)
                    if !row.required {
                        Text("optional").font(.system(size: 11)).foregroundStyle(Presence.faint)
                    }
                }
                Text(row.reason)
                    .font(.system(size: 13))
                    .foregroundStyle(Presence.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if case .openSettings(let why) = row.action {
                    Text(why).font(.system(size: 12)).foregroundStyle(Presence.warn)
                }
                if case .unavailable(let why) = row.action {
                    Text(why).font(.system(size: 12)).foregroundStyle(Presence.muted)
                }
            }
            Spacer(minLength: 8)
            if let title = buttonTitle {
                Button(title, action: act)
                    .buttonStyle(CompactPill(filled: row.required))
                    .accessibilityIdentifier("\(row.id)-action")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 14)
    }

    private var buttonTitle: String? {
        switch row.action {
        case .pair: return "Pair"
        case .allow: return "Allow"
        case .openSettings: return "Settings"
        case .done, .unavailable: return nil
        }
    }

    private var icon: String {
        switch row.action {
        case .done: return "checkmark.circle.fill"
        case .openSettings: return "exclamationmark.circle"
        case .unavailable: return "nosign"
        case .pair, .allow: return "circle"
        }
    }

    private var color: Color {
        switch row.action {
        case .done: return Presence.green
        case .openSettings: return Presence.warn
        default: return Presence.faint
        }
    }
}

/// A small pill for a row's button ("Pair", "Allow").
struct CompactPill: ButtonStyle {
    var filled = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(filled ? Color.white : Presence.ink)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Capsule().fill(filled ? Presence.greenDeep : Presence.raised))
            .overlay(Capsule().strokeBorder(filled ? Color.clear : Presence.line, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

/// Pair this iPhone: paste the pairing link, or type the code and the address.
struct PairView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var entry = ""
    @State private var server = ""
    @State private var problem: String?
    @State private var working = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("In the Ira web app, open the menu, Your devices. Under Add a device choose iPhone, type your PIN and make a pairing code. Then copy the link and paste it here, or type the code and your Ira's address.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Section("Pairing link or code") {
                    TextField("https://…/pair#code=ABCD-EFGH, or ABCD-EFGH", text: $entry, axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .accessibilityIdentifier("pair-entry")
                    PasteButton(payloadType: String.self) { strings in
                        if let first = strings.first { entry = first }
                    }
                }
                Section {
                    TextField("https://ira.example.com", text: $server)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .accessibilityIdentifier("pair-server")
                } header: {
                    Text("Your Ira's address")
                } footer: {
                    Text("Only needed with a typed code. The code works once, within 10 minutes.")
                }
                if let problem {
                    Section {
                        Label(problem, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(Presence.down)
                            .accessibilityIdentifier("pair-problem")
                    }
                }
                Section {
                    Button {
                        Task { await pair() }
                    } label: {
                        HStack {
                            Spacer()
                            if working { ProgressView().padding(.trailing, 6) }
                            Text(working ? StepWords.pairing : "Pair")
                            Spacer()
                        }
                    }
                    .disabled(working || entry.trimmingCharacters(in: .whitespaces).isEmpty)
                    .accessibilityIdentifier("pair-button")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Presence.bg)
            .navigationTitle("Pair this iPhone")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
    }

    private func pair() async {
        working = true
        problem = nil
        problem = await model.pair(entry: entry, server: server)
        working = false
        if problem == nil { dismiss() }
    }
}
