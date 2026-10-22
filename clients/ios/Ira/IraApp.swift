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
