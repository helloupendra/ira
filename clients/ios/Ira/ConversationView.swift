import IraPhoneKit
import SwiftUI

/// The conversation: the lens and the greeting when it is empty, else Ira's answers with
/// their receipts and proposals; the ask pill at the bottom; a call over the whole screen.
struct ConversationView: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""
    @State private var reporting: Entry?
    @State private var showingSettings = false
    @State private var typingInCall = false
    @FocusState private var typing: Bool

    private var talk: TalkController { model.talk }

    var body: some View {
        ZStack {
            Presence.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                if let notice = model.notice {
                    NoticeBar(text: notice) { model.notice = nil }
                        .padding(.horizontal, 16)
                        .padding(.top, 6)
                }
                if talk.transcript.entries.isEmpty && talk.step == nil {
                    Hero(name: model.assistantName, status: statusLine, cards: nowCards)
                } else {
                    messages
                }
                AskPill(
                    placeholder: "Ask \(model.assistantName), or tap the call button",
                    draft: $draft, typing: $typing, send: send,
                    call: {
                        typing = false
                        talk.toggleCall()
                    })
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .padding(.bottom, 10)
            }
            if talk.inCall {
                CallView(typing: $typingInCall)
                    .transition(.opacity)
                    .zIndex(1)
            }
        }
        .animation(.easeOut(duration: 0.2), value: talk.inCall)
        .navigationTitle(model.assistantName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Presence.bg, for: .navigationBar)
        .toolbar(talk.inCall ? .hidden : .visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    talk.newConversation()
                } label: {
                    Label("New conversation", systemImage: "square.and.pencil")
                }
                .tint(Presence.ink)
            }
            ToolbarItem(placement: .principal) {
                VStack(spacing: 1) {
                    Text(model.assistantName).font(.system(size: 16, weight: .semibold)).foregroundStyle(Presence.ink)
                    HStack(spacing: 5) {
                        Circle().fill(connected ? Presence.green : Presence.warn).frame(width: 6, height: 6)
                        Text(connected ? "Connected" : "Tools offline").font(.system(size: 11)).foregroundStyle(Presence.muted)
                    }
                }
                .accessibilityElement(children: .combine)
            }
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink {
                    DropView()
                } label: {
                    Label("Drop", systemImage: "tray.and.arrow.down")
                }
                .tint(Presence.ink)
                .accessibilityIdentifier("drop")
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showingSettings = true
                } label: {
                    Label("Settings", systemImage: "gearshape")
                }
                .tint(Presence.ink)
                .accessibilityIdentifier("settings")
            }
        }
        .sheet(item: $reporting) { entry in ReportSheet(entry: entry) }
        .sheet(isPresented: $showingSettings) { SettingsView() }
    }

    private var connected: Bool {
        if case .connected = model.deviceState { return true }
        return false
    }

    /// The date, and how this iPhone is with Ira, under the greeting.
    private var statusLine: String {
        let day = Date().formatted(.dateTime.weekday(.wide).day().month(.wide))
        if let line = Plain.device(model.deviceState) { return "\(day) · \(line)" }
        return connected ? "\(day) · this iPhone is connected" : day
    }

    /// Only what is real now: the newest Drop item. Never filler.
    private var nowCards: [NowCard] {
        guard let latest = model.drop.items.first else { return [] }
        let from = latest.fromLabel.isEmpty ? "Your Drop" : "From \(latest.fromLabel)"
        return [NowCard(label: "Drop", value: latest.preview, detail: from)]
    }

    private var messages: some View {
        ScrollViewReader { scroller in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(talk.transcript.entries) { entry in
                        EntryView(entry: entry, report: { reporting = entry })
                            .id(entry.id)
                    }
                    if let step = talk.step, !talk.inCall {
                        ThinkingRow(step: step, since: talk.stepStarted)
                            .id("thinking")
                    }
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 16)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: talk.transcript.entries.last?.text) { _, _ in
                if let last = talk.transcript.entries.last {
                    withAnimation { scroller.scrollTo(last.id, anchor: .bottom) }
                }
            }
            .onChange(of: talk.step) { _, step in
                if step != nil { withAnimation { scroller.scrollTo("thinking", anchor: .bottom) } }
            }
        }
    }

    private func send() {
        talk.send(draft)
        draft = ""
    }
}

/// An empty conversation: the lens, the greeting, the date and how Ira is, what is worth
/// knowing now, and a few things to try.
struct Hero: View {
    let name: String
    let status: String
    var cards: [NowCard] = []
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            HeroContent(name: name, status: status, cards: cards)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(
            RadialGradient(
                colors: [Color(hex: 0x1F6F5C, opacity: scheme == .dark ? 0.18 : 0.10), .clear],
                center: UnitPoint(x: 0.5, y: 0.2), startRadius: 0, endRadius: 320))
    }
}

/// What the hero shows, without its scrolling (so a snapshot can draw it).
struct HeroContent: View {
    let name: String
    let status: String
    var cards: [NowCard] = []

    var body: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 28)
            Lens(size: 92, breathing: true, rings: 1)
            VStack(spacing: 8) {
                Greeting()
                Text(status)
                    .font(Presence.secondary)
                    .foregroundStyle(Presence.muted)
                    .multilineTextAlignment(.center)
            }
            if !cards.isEmpty {
                VStack(spacing: 10) {
                    ForEach(Array(cards.enumerated()), id: \.offset) { _, card in card }
                }
                .padding(.top, 6)
            }
            VStack(spacing: 6) {
                Text("Hindi, English or Hinglish. Try:")
                    .font(.system(size: 13))
                    .foregroundStyle(Presence.muted)
                ForEach(["“kal ka schedule kya hai?”", "“98100 00000 kiska number hai?”", "“kal subah 9 baje yaad dilana”"], id: \.self) {
                    Text($0).font(Presence.serif(16).italic()).foregroundStyle(Presence.ink.opacity(0.8))
                }
                Text("“Hey Siri, Ask \(name)” works too.")
                    .font(.system(size: 12))
                    .foregroundStyle(Presence.faint)
                    .padding(.top, 4)
            }
            .padding(.top, 10)
            Spacer(minLength: 16)
        }
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
    }
}

/// The ask pill: type, or tap the call button and talk; the button turns into Send while there
/// is text.
struct AskPill: View {
    let placeholder: String
    @Binding var draft: String
    var typing: FocusState<Bool>.Binding
    let send: () -> Void
    let call: () -> Void

    private var hasText: Bool { !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(placeholder, text: $draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(Presence.body)
                .foregroundStyle(Presence.ink)
                .lineLimit(1...5)
                .focused(typing)
                .submitLabel(.send)
                .onSubmit { if hasText { send() } }
                .padding(.vertical, 11)
                .accessibilityIdentifier("ask-field")
            Button {
                hasText ? send() : call()
            } label: {
                Image(systemName: hasText ? "arrow.up" : "waveform")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(Circle().fill(Presence.greenDeep))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(hasText ? "Send" : "Call Ira")
            .accessibilityIdentifier(hasText ? "send-button" : "call")
        }
        .padding(.leading, 20)
        .padding(.trailing, 5)
        .padding(.vertical, 5)
        .background(RoundedRectangle(cornerRadius: 26).fill(Presence.raised))
        .overlay(RoundedRectangle(cornerRadius: 26).strokeBorder(Presence.line, lineWidth: 1))
    }
}

/// While an answer is on its way: the lens's bars ripple, with what Ira is doing.
struct ThinkingRow: View {
    let step: String
    let since: Date?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 12) {
                Lens(size: 26, thinking: true)
                Text(label(at: context.date))
                    .font(Presence.secondary)
                    .foregroundStyle(Presence.muted)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("busy")
        }
    }

    func label(at now: Date) -> String {
        guard let since else { return step }
        let seconds = Int(now.timeIntervalSince(since))
        if seconds >= 30 { return "No answer yet. Your Ira is slow or unreachable." }
        return seconds >= 3 ? "\(step) \(seconds) s" : step
    }
}

/// The call, over the whole conversation, with the proposal that needs an answer now and
/// typing into the call.
struct CallView: View {
    @Environment(AppModel.self) private var model
    @Binding var typing: Bool
    @State private var draft = ""
    @FocusState private var focused: Bool

    private var talk: TalkController { model.talk }

    var body: some View {
        CallStage(
            phase: talk.phase, level: talk.level, levels: talk.levels.levels, caption: talk.caption,
            answer: latestAnswer, live: talk.mode == .live,
            onEnd: { talk.endCall() }, onStop: { talk.stop() },
            onRetry: {
                talk.endCall()
                talk.startCall()
            },
            onKeyboard: {
                typing.toggle()
                focused = typing
            }
        ) {
            VStack(spacing: 10) {
                if let card = openCard {
                    ActionCardView(card: card)
                }
                if typing {
                    AskPill(
                        placeholder: "Type into the call", draft: $draft, typing: $focused,
                        send: {
                            talk.send(draft)
                            draft = ""
                        },
                        call: { focused = false })
                }
            }
        }
    }

    /// Ira's latest answer, while this call goes on.
    private var latestAnswer: String {
        talk.transcript.entries.last { $0.role == .ira }?.text ?? ""
    }

    /// A proposal still waiting for the person, newest first: it is answered in the call too.
    private var openCard: ActionCard? {
        guard let card = talk.transcript.entries.last(where: { $0.action != nil })?.action else { return nil }
        switch card.need {
        case .yes, .pin: return card
        default: return nil
        }
    }
}

struct NoticeBar: View {
    let text: String
    let close: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle").foregroundStyle(Presence.warn)
            Text(text)
                .font(Presence.secondary)
                .foregroundStyle(Presence.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: close) { Image(systemName: "xmark").foregroundStyle(Presence.muted) }
                .accessibilityLabel("Close")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14).fill(Presence.warn.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Presence.warn.opacity(0.45), lineWidth: 1))
        .accessibilityIdentifier("notice")
    }
}

/// One line: what you said, what Ira answered (with its receipts and Report), or a note.
struct EntryView: View {
    let entry: Entry
    let report: () -> Void

    var body: some View {
        switch entry.role {
        case .you:
            HStack {
                Spacer(minLength: 48)
                Text(entry.text)
                    .font(Presence.body)
                    .foregroundStyle(Presence.ink)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 18).fill(Presence.raised))
                    .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Presence.line, lineWidth: 1))
                    .textSelection(.enabled)
            }
        case .ira:
            AnswerRow(entry: entry, report: report)
        case .note:
            if let card = entry.action {
                ActionCardView(card: card)
            } else {
                Text(entry.text)
                    .font(.system(size: 13))
                    .foregroundStyle(Presence.muted)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .multilineTextAlignment(.center)
            }
        }
    }
}

/// Ira's answer: the small lens, the words, and under them the tools she used.
struct AnswerRow: View {
    let entry: Entry
    var report: () -> Void = {}

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Lens(size: 26, thinking: entry.streaming && entry.text.isEmpty)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 8) {
                Text(entry.text.isEmpty ? "…" : entry.text)
                    .font(Presence.body)
                    .foregroundStyle(Presence.ink)
                    .lineSpacing(3)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contextMenu {
                        if entry.canReport {
                            Button("Report this answer…", systemImage: "flag", action: report)
                        }
                    }
                    .accessibilityIdentifier("answer")
                if !entry.tools.isEmpty || entry.canReport || entry.reported {
                    HStack(spacing: 6) {
                        ForEach(entry.tools.prefix(4), id: \.self) { ReceiptChip(text: $0) }
                        Spacer(minLength: 0)
                        if entry.canReport {
                            Menu {
                                Button("Report this answer…", systemImage: "flag", action: report)
                            } label: {
                                Image(systemName: "ellipsis")
                                    .foregroundStyle(Presence.muted)
                                    .frame(width: 30, height: 22)
                            }
                            .accessibilityLabel("More")
                        } else if entry.reported {
                            Text("Reported").font(.system(size: 11)).foregroundStyle(Presence.muted)
                        }
                    }
                }
            }
        }
    }
}

/// A proposal: what Ira wants to do, exactly, and what it needs first. Tier 2: Yes or No
/// (or say "haan" / "nahi" in a call). Tier 3: the PIN, typed here, never spoken; it goes only
/// to your Ira's confirm step.
struct ActionCardView: View {
    @Environment(AppModel.self) private var model
    let card: ActionCard
    @State var pin = ""

    private var talk: TalkController { model.talk }

    var body: some View {
        ProposalCard(
            card: card, pin: $pin, deciding: talk.deciding.contains(card.id), outcome: talk.outcomes[card.id],
            answer: { talk.answer(card, yes: $0) },
            confirm: {
                talk.confirm(card, pin: pin)
                pin = ""  // the PIN is never kept
            })
    }
}

/// The proposal's card itself, from plain values.
struct ProposalCard: View {
    let card: ActionCard
    @Binding var pin: String
    var deciding = false
    var outcome: String?
    var answer: (Bool) -> Void = { _ in }
    var confirm: () -> Void = {}

    private var needsPIN: Bool { card.tier >= 3 }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            DotLabel(text: needsPIN ? "Needs your PIN" : "Needs your yes", color: Presence.warn)
            Text(card.summary)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(Presence.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(card.statusWords)
                .font(.system(size: 12))
                .foregroundStyle(Presence.muted)
            switch card.need {
            case .yes:
                HStack(spacing: 10) {
                    Button("Yes, do it") { answer(true) }
                        .buttonStyle(PillButtonStyle(filled: true))
                        .accessibilityIdentifier("action-yes")
                    Button("No") { answer(false) }
                        .buttonStyle(PillButtonStyle())
                        .accessibilityIdentifier("action-no")
                }
                .disabled(deciding)
            case .pin:
                PINField(pin: $pin)
                HStack(spacing: 10) {
                    Button("Confirm") { confirm() }
                        .buttonStyle(PillButtonStyle(filled: true))
                        .disabled(pin.count < 4 || deciding)
                    Button("Cancel") { answer(false) }
                        .buttonStyle(PillButtonStyle())
                }
                Text("Type your PIN; never say it aloud.")
                    .font(.system(size: 12))
                    .foregroundStyle(Presence.muted)
            case .cannot(let why):
                Text(why).font(.system(size: 13)).foregroundStyle(Presence.muted)
            case .settled:
                EmptyView()
            }
            if let outcome {
                Text(outcome)
                    .font(.system(size: 13))
                    .foregroundStyle(Presence.ink)
                    .accessibilityIdentifier("action-outcome")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18).fill(Presence.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Presence.warn.opacity(0.45), lineWidth: 1))
    }
}

/// The PIN, typed into four to twelve dots: the field itself is hidden, the dots show how many.
struct PINField: View {
    @Binding var pin: String
    @FocusState private var focused: Bool

    var body: some View {
        ZStack(alignment: .leading) {
            SecureField("", text: $pin)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .focused($focused)
                .opacity(0.02)
                .accessibilityIdentifier("action-pin")
                .onChange(of: pin) { _, now in
                    let digits = String(now.filter(\.isNumber).prefix(12))
                    if digits != now { pin = digits }
                }
            HStack(spacing: 12) {
                ForEach(0..<max(4, min(pin.count + (pin.count < 12 ? 1 : 0), 12)), id: \.self) { index in
                    Circle()
                        .fill(index < pin.count ? Presence.ink : Color.clear)
                        .overlay(Circle().strokeBorder(index < pin.count ? Color.clear : Presence.muted, lineWidth: 1.2))
                        .frame(width: 13, height: 13)
                }
            }
            .padding(.horizontal, 16)
            .frame(height: 46)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(Presence.raised))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(focused ? Presence.green : Presence.line, lineWidth: 1))
            .contentShape(Rectangle())
            .onTapGesture { focused = true }
            .accessibilityHidden(true)
        }
    }
}

/// Report an answer that is wrong, harmful, offensive or private. It goes to the
/// person who runs your Ira, with that answer; nothing else is sent.
struct ReportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let entry: Entry
    @State var reason: ReportReason = .wrong
    @State var note = ""
    @State var problem: String?
    @State var sending = false

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
                    Section { Label(problem, systemImage: "exclamationmark.triangle").foregroundStyle(Presence.down) }
                }
                Section {
                    Text("The report goes to the person who runs your Ira, with this answer. Nothing else is sent.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Presence.bg)
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
