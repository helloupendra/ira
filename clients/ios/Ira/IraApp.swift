import IraPhoneKit
import SwiftUI

@main
struct IraApp: App {
    @State private var model = AppModel.shared
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .onOpenURL { url in Task { await model.open(url) } }
                .onChange(of: phase) { _, now in model.phaseChanged(now) }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            if model.showingSetup {
                SetupView()
            } else {
                ConversationView()
            }
        }
        .overlay(alignment: .bottom) {
            if let busy = model.busy {
                BusyLine(text: busy, since: nil)
                    .padding(.bottom, 90)
                    .transition(.opacity)
            }
        }
        .animation(.default, value: model.busy)
        .sheet(item: $model.linkToConfirm) { link in LinkPairSheet(link: link) }
    }
}

/// "Pair with this Ira?": a pairing link opened from another app or a web page. Pairing
/// sends what this iPhone asks, and what Ira may use on it, to that server.
struct LinkPairSheet: View {
    @Environment(AppModel.self) private var model
    let link: LinkPair

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(link.server)
                        .font(.body.monospaced())
                        .textSelection(.enabled)
                        .accessibilityIdentifier("link-server")
                } header: {
                    Text("A link asks to pair this iPhone with")
                } footer: {
                    Text("Pair only if you made this code yourself, on your own Ira, just now.")
                }
                if let current = link.current {
                    Section {
                        Text(current)
                            .font(.body.monospaced())
                            .accessibilityIdentifier("link-current")
                    } header: {
                        Text("It is paired with")
                    } footer: {
                        Text("Pairing with the link forgets that Ira on this iPhone. Your data there stays.")
                    }
                }
            }
            .navigationTitle("Pair with this Ira?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { model.linkToConfirm = nil }
                        .accessibilityIdentifier("link-cancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Pair") { Task { await model.pairWithLink() } }
                        .accessibilityIdentifier("link-pair")
                }
            }
        }
        .interactiveDismissDisabled()
    }
}

/// A busy line that names the step, and the seconds after three.
struct BusyLine: View {
    let text: String
    let since: Date?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            HStack(spacing: 8) {
                ProgressView()
                Text(label(at: context.date))
                    .font(.callout)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(.thinMaterial, in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("busy")
        }
    }

    func label(at now: Date) -> String {
        guard let since else { return text }
        let seconds = Int(now.timeIntervalSince(since))
        if seconds >= 30 { return "No answer yet. Your Ira is slow or unreachable." }
        return seconds >= 3 ? "\(text) \(seconds) s" : text
    }
}
