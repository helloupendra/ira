import IraPhoneKit
import SwiftUI

/// "Get Ira ready": pair, the microphone, speech recognition, then each skill,
/// each with one line on why, and the button that does it.
struct SetupView: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = false

    var body: some View {
        List {
            Section {
                Text("Ira for iPhone talks to your own Ira. Do these once; only Pair and Microphone are needed to talk.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            if let notice = model.notice {
                Section {
                    Label(notice, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                        .accessibilityIdentifier("notice")
                }
            }
            Section("Get Ira ready") {
                ForEach(model.rows) { row in
                    ChecklistRowView(row: row) { act(on: row) }
                }
            }
            Section {
            } footer: {
                Text("You can allow the rest later: Settings, Get Ira ready. iOS lets no app read your calls, SMS or other apps' notifications, so Ira for iPhone never asks for them.")
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button {
                model.finishSetup()
            } label: {
                Text(model.ready ? "Start talking to \(model.assistantName)" : "Pair and allow the microphone first")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!model.ready)
            .accessibilityIdentifier("start")
            .padding()
            .background(.bar)
        }
        .navigationTitle("Get Ira ready")
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

struct ChecklistRowView: View {
    let row: ChecklistRow
    let act: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(color)
                .font(.title3)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 4) {
                Text(row.title + (row.required ? "" : " (optional)"))
                    .font(.headline)
                Text(row.reason)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if case .openSettings(let why) = row.action {
                    Text(why).font(.footnote).foregroundStyle(.orange)
                }
                if case .unavailable(let why) = row.action {
                    Text(why).font(.footnote).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 8)
            if let title = buttonTitle {
                Button(title, action: act)
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("\(row.id)-action")
            }
        }
        .padding(.vertical, 4)
    }

    private var buttonTitle: String? {
        switch row.action {
        case .pair: return "Pair"
        case .allow: return "Allow"
        case .openSettings: return "Open Settings"
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
        case .done: return .green
        case .openSettings: return .orange
        default: return .secondary
        }
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
                            .foregroundStyle(.red)
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
