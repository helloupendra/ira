import IraPhoneKit
import SwiftUI

/// The conversation: Ira's answers, typing, the call button, and proposals.
struct ConversationView: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""
    @State private var reporting: Entry?
    @State private var showingSettings = false
    @FocusState private var typing: Bool

    private var talk: TalkController { model.talk }

    var body: some View {
        VStack(spacing: 0) {
            if let notice = model.notice {
                NoticeBar(text: notice) { model.notice = nil }
            }
            if let line = Plain.device(model.deviceState) {
                Text(line)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal)
                    .padding(.vertical, 4)
            }
            messages
            if talk.inCall || talk.step != nil {
                CallStatus()
            }
            inputBar
        }
        .navigationTitle(model.assistantName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    talk.newConversation()
                } label: {
                    Label("New conversation", systemImage: "square.and.pencil")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showingSettings = true
                } label: {
                    Label("Settings", systemImage: "gearshape")
                }
                .accessibilityIdentifier("settings")
            }
        }
        .sheet(item: $reporting) { entry in ReportSheet(entry: entry) }
        .sheet(isPresented: $showingSettings) { SettingsView() }
    }

    private var messages: some View {
        ScrollViewReader { scroller in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if talk.transcript.entries.isEmpty {
                        EmptyConversation(name: model.assistantName)
                    }
                    ForEach(talk.transcript.entries) { entry in
                        EntryView(entry: entry, report: { reporting = entry })
                            .id(entry.id)
                    }
                }
                .padding()
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: talk.transcript.entries.last?.text) { _, _ in
                if let last = talk.transcript.entries.last {
                    withAnimation { scroller.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField(talk.inCall ? "Type into the call" : "Ask \(model.assistantName)", text: $draft, axis: .vertical)
                .lineLimit(1...5)
                .textFieldStyle(.roundedBorder)
                .focused($typing)
                .submitLabel(.send)
                .onSubmit(send)
                .accessibilityIdentifier("ask-field")
            if !draft.trimmingCharacters(in: .whitespaces).isEmpty {
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill").font(.title)
                }
                .accessibilityLabel("Send")
                .accessibilityIdentifier("send")
            }
            Button {
                typing = false
                talk.toggleCall()
            } label: {
                Image(systemName: talk.inCall ? "phone.down.circle.fill" : "phone.circle.fill")
                    .font(.largeTitle)
                    .foregroundStyle(talk.inCall ? Color.red : Color.accentColor)
            }
            .accessibilityLabel(talk.inCall ? "End call" : "Call \(model.assistantName)")
            .accessibilityIdentifier("call")
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private func send() {
        talk.send(draft)
        draft = ""
    }
}

struct EmptyConversation: View {
    let name: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Type, or tap the phone to talk.")
                .font(.headline)
            Text("Hindi, English or Hinglish. For example:")
                .foregroundStyle(.secondary)
            Text("“kal ka schedule kya hai?”\n“98100 00000 kiska number hai?”\n“kal subah 9 baje yaad dilana”")
                .foregroundStyle(.secondary)
            Text("“Hey Siri, Ask \(name)” works too.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .padding(.top, 4)
        }
        .padding(.vertical, 24)
    }
}

/// The call's state, how it talks to Ira, and what Ira is doing now.
struct CallStatus: View {
    @Environment(AppModel.self) private var model
    private var talk: TalkController { model.talk }

    var body: some View {
        VStack(spacing: 6) {
            if let step = talk.step {
                BusyLine(text: step, since: talk.stepStarted)
            }
            if talk.inCall {
                HStack(spacing: 10) {
                    Circle()
                        .fill(Color.accentColor)
                        .frame(width: 12 + CGFloat(min(talk.level * 120, 18)), height: 12 + CGFloat(min(talk.level * 120, 18)))
                        .animation(.easeOut(duration: 0.1), value: talk.level)
                    Text(callWords)
                        .font(.callout)
                    Spacer()
                    if talk.speaking || talk.step != nil {
                        Button("Stop") { talk.stop() }
                            .buttonStyle(.bordered)
                            .accessibilityIdentifier("stop")
                    }
                }
                if !talk.caption.isEmpty {
                    Text(talk.caption)
                        .font(.callout.italic())
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                if let mode = talk.mode {
                    Text(mode.explanation)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("mode")
                }
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 6)
    }

    private var callWords: String {
        switch talk.callState {
        case .idle: return ""
        case .connecting: return "Connecting…"
        case .listening(let hearing):
            if talk.speaking { return "\(model.assistantName) is speaking" }
            return hearing ? "Hearing you…" : "Listening"
        }
    }
}

struct NoticeBar: View {
    let text: String
    let close: () -> Void

    var body: some View {
        HStack(alignment: .top) {
            Image(systemName: "exclamationmark.triangle").foregroundStyle(.orange)
            Text(text).font(.callout).frame(maxWidth: .infinity, alignment: .leading)
            Button(action: close) { Image(systemName: "xmark") }
                .accessibilityLabel("Close")
        }
        .padding(10)
        .background(Color.orange.opacity(0.12))
        .accessibilityIdentifier("notice")
    }
}

/// One line: what you said, what Ira answered (with Report), or a note.
struct EntryView: View {
    let entry: Entry
    let report: () -> Void

    var body: some View {
        switch entry.role {
        case .you:
            HStack {
                Spacer(minLength: 40)
                Text(entry.text)
                    .padding(10)
                    .background(Color.accentColor.opacity(0.18), in: RoundedRectangle(cornerRadius: 14))
                    .textSelection(.enabled)
            }
        case .ira:
            HStack(alignment: .bottom) {
                Text(entry.text.isEmpty ? "…" : entry.text)
                    .padding(10)
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
                    .textSelection(.enabled)
                    .contextMenu {
                        if entry.canReport {
                            Button("Report this answer…", systemImage: "flag", action: report)
                        }
                    }
                    .accessibilityIdentifier("answer")
                if entry.canReport {
                    Menu {
                        Button("Report this answer…", systemImage: "flag", action: report)
                    } label: {
                        Image(systemName: "ellipsis")
                            .foregroundStyle(.secondary)
                            .padding(6)
                    }
                    .accessibilityLabel("More")
                } else if entry.reported {
                    Text("Reported").font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 24)
            }
        case .note:
            if let card = entry.action {
                ActionCardView(card: card)
            } else {
                Text(entry.text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .multilineTextAlignment(.center)
            }
        }
    }
}

/// A proposal: what Ira wants to do, exactly, and what it needs first. Tier 2:
/// Yes or No (or say "haan" / "nahi" in a call). Tier 3: the PIN, typed here,
/// never spoken; it goes only to your Ira's confirm step.
struct ActionCardView: View {
    @Environment(AppModel.self) private var model
    let card: ActionCard
    @State private var pin = ""

    private var talk: TalkController { model.talk }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(card.tier >= 3 ? "Needs your PIN" : "Needs your yes", systemImage: card.tier >= 3 ? "lock" : "hand.raised")
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            Text(card.summary)
                .font(.body)
            Text(card.statusWords)
                .font(.footnote)
                .foregroundStyle(.secondary)
            switch card.need {
            case .yes:
                HStack {
                    Button("Yes") { talk.answer(card, yes: true) }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("action-yes")
                    Button("No") { talk.answer(card, yes: false) }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("action-no")
                }
                .disabled(talk.deciding.contains(card.id))
            case .pin:
                HStack {
                    SecureField("Action PIN", text: $pin)
                        .keyboardType(.numberPad)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 160)
                        .accessibilityIdentifier("action-pin")
                    Button("Confirm") {
                        talk.confirm(card, pin: pin)
                        pin = ""  // the PIN is never kept
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(pin.count < 4 || talk.deciding.contains(card.id))
                    Button("Cancel") { talk.answer(card, yes: false) }
                        .buttonStyle(.bordered)
                }
                Text("Type your PIN; never say it aloud.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .cannot(let why):
                Text(why).font(.footnote).foregroundStyle(.secondary)
            case .settled:
                EmptyView()
            }
            if let outcome = talk.outcomes[card.id] {
                Text(outcome)
                    .font(.footnote)
                    .accessibilityIdentifier("action-outcome")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).strokeBorder(Color.accentColor.opacity(0.5)))
    }
}

/// Report an answer that is wrong, harmful, offensive or private. It goes to the
/// person who runs your Ira, with that answer; nothing else is sent.
struct ReportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let entry: Entry
    @State private var reason: ReportReason = .wrong
    @State private var note = ""
    @State private var problem: String?
    @State private var sending = false

    var body: some View {
        NavigationStack {
            Form {
                Section("The answer") {
                    Text(entry.text).font(.callout).foregroundStyle(.secondary).lineLimit(6)
                }
                Section("What is wrong with it?") {
                    Picker("Reason", selection: $reason) {
                        ForEach(ReportReason.allCases) { Text($0.words).tag($0) }
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                    TextField("A note (optional)", text: $note, axis: .vertical)
                        .lineLimit(1...4)
                }
                if let problem {
                    Section { Label(problem, systemImage: "exclamationmark.triangle").foregroundStyle(.red) }
                }
                Section {
                    Text("The report goes to the person who runs your Ira, with this answer. Nothing else is sent.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(sending ? "Sending…" : "Send") {
                        Task {
                            sending = true
                            problem = await model.talk.report(entry, reason: reason, note: note)
                            sending = false
                            if problem == nil { dismiss() }
                        }
                    }
                    .disabled(sending)
                }
            }
        }
    }
}
