import AppKit
import IraKit
import SwiftUI

final class SetupState: ObservableObject {
    @Published var step = 2
    @Published var working = false
    @Published var problem: String?
    @Published var asked = false
    @Published var openAtLogin = true
}

/// The first run, as a checklist: pair (or take over the old companion), allow
/// what Ira needs one by one, then ask a test question.
struct SetupView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    @ObservedObject var permissions: PermissionCenter
    @StateObject private var state = SetupState()

    init(model: AppModel, conversation: Conversation) {
        self.model = model
        self.conversation = conversation
        self.permissions = model.permissions
    }

    private var step: Int { model.paired && !model.repairing ? state.step : 1 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                ForEach(Array(["Pair", "Allow", "Try it"].enumerated()), id: \.offset) { index, title in
                    let number = index + 1
                    HStack(spacing: 4) {
                        Image(systemName: number < step ? "checkmark.circle.fill" : "\(number).circle\(number == step ? ".fill" : "")")
                            .foregroundStyle(number <= step ? Color.iraText : Color.secondary)
                        Text(title).font(.caption.weight(number == step ? .semibold : .regular))
                    }
                    if number < 3 { Rectangle().fill(Color.secondary.opacity(0.3)).frame(height: 1) }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 34)
            .padding(.bottom, 8)
            Divider()
            switch step {
            case 1: pairStep
            case 2: allowStep
            default: tryStep
            }
        }
    }

    // MARK: 1. Pair

    @ViewBuilder private var pairStep: some View {
        if model.companionPresent && !model.paired && !model.repairing {
            VStack(alignment: .leading, spacing: 14) {
                Header(title: "The old Ira companion is on this Mac")
                Text(companionText)
                    .fixedSize(horizontal: false, vertical: true)
                if model.companion?.server.isEmpty == false {
                    Button(state.working ? "Taking over…" : "Use its pairing and remove it") { takeOver() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(state.working)
                }
                Button("Remove it and pair Ira for Mac with a new code") { removeCompanion() }
                    .disabled(state.working)
                if let problem = state.problem {
                    Label(problem, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Text("Ira for Mac replaces the companion and the Chrome extension: it reads your browser tabs itself. Afterwards, remove the Ira extension in chrome://extensions.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(20)
        } else {
            PairView(model: model)
        }
    }

    private var companionText: String {
        guard let found = model.companion, !found.server.isEmpty else {
            return "It is not paired with any Ira. Remove it, then pair Ira for Mac with a code from Your devices."
        }
        let host = URL(string: found.server)?.host ?? found.server
        return "It is paired with \(host) as “\(found.label)”. Ira for Mac can take over that pairing, so you do not need a new code, and named networks keep their names. Then it stops the companion and removes it from this Mac."
    }

    private func takeOver() {
        state.working = true
        state.problem = nil
        Task {
            do {
                try await model.takeOverCompanion()
            } catch {
                state.problem = "Not taken over: \(error.localizedDescription)"
            }
            state.working = false
        }
    }

    private func removeCompanion() {
        state.working = true
        Task {
            await model.removeCompanion()
            state.working = false
        }
    }

    // MARK: 2. Allow

    private var allowStep: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Header(title: "What Ira may use on this Mac")
                    Text("Ira reads nothing until you ask. Allow what you want Ira to help with; skip the rest. You can change your mind in System Settings → Privacy & Security at any time.")
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(permissions.all.filter { $0.id != "speech" }) { permission in
                        PermissionRow(
                            permission: permission,
                            ask: { Task { await permissions.ask(permission) } },
                            open: { permissions.open(permission) })
                    }
                    Text("Coding tasks, if you set them up, work in your repositories; macOS asks once for the Documents folder when the first one starts.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Then, on your Ira's **Your devices** page, switch on the skills you want this Mac to have: Files, Screen, Browser, Contacts, Calendar and the others. Each needs your PIN.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(20)
            }
            Divider()
            HStack {
                Button("Check again") { permissions.refresh() }
                Spacer()
                Button("Next") { state.step = 3 }
                    .keyboardShortcut(.defaultAction)
            }
            .padding(12)
        }
        .onAppear { permissions.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            permissions.refresh()
        }
    }

    // MARK: 3. Try it

    private var answer: String? {
        conversation.entries.last(where: { $0.role == .ira })?.text
    }

    private var tryStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Header(title: "Ask Ira something")
            Text("A test question checks the whole way: this Mac, your Ira and its answer.")
                .fixedSize(horizontal: false, vertical: true)
            Button("Ask: “What can you do on this Mac?”") {
                state.asked = true
                conversation.send("What can you do on this Mac?")
            }
            .disabled(state.asked && answer == nil && conversation.notice == nil)
            if let answer {
                Text(answer)
                    .textSelection(.enabled)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                Label("It works.", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            } else if state.asked, let notice = conversation.notice {
                Label(notice, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            } else if state.asked {
                ProgressView().controlSize(.small)
            }
            Toggle("Open Ira when I log in", isOn: $state.openAtLogin)
            Spacer()
            HStack {
                Button("Back") { state.step = 2 }
                Spacer()
                Button("Finish") {
                    if let problem = LoginItem.set(state.openAtLogin), state.openAtLogin {
                        conversation.notice = problem
                    }
                    model.finishFirstRun()
                }
                .keyboardShortcut(.defaultAction)
            }
            Text("Press \(HotKey.describe(keyCode: model.settings.hotKeyCode, modifiers: model.settings.hotKeyModifiers)) anywhere to open Ira.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(20)
    }
}
