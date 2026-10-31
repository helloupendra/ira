import AppKit
import IraKit
import SwiftUI

/// The parts of Ira's window, in its sidebar.
enum Pane: String, CaseIterable, Identifiable {
    case chat, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .chat: return "Chat"
        case .settings: return "Settings"
        }
    }

    var icon: String {
        switch self {
        case .chat: return "bubble.left.and.bubble.right"
        case .settings: return "gearshape"
        }
    }
}

/// What the sidebar has selected: a part of the window, or one of today's conversations.
enum SidebarItem: Hashable {
    case pane(Pane)
    case conversation(String)
}

/// The window's own state: the part shown, kept for the next launch.
@MainActor
final class WindowState: ObservableObject {
    private static let key = "windowPane"

    @Published var selection: SidebarItem? {
        didSet {
            if case .pane(let pane) = selection { UserDefaults.standard.set(pane.rawValue, forKey: WindowState.key) }
        }
    }

    init() {
        let saved = UserDefaults.standard.string(forKey: WindowState.key).flatMap(Pane.init(rawValue:)) ?? .chat
        selection = .pane(saved)
    }

    var pane: Pane {
        if case .pane(let pane) = selection { return pane }
        return .chat
    }
}

/// Ira's one window: a sidebar (Chat, Settings and today's conversations) and the part chosen.
/// Before this Mac is paired, the whole window is the first-run setup.
struct AppWindowView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var conversation: Conversation
    @ObservedObject var state: WindowState
    let hotKeyChanged: () -> Void

    var body: some View {
        Group {
            switch model.screen {
            case .setup:
                SetupView(model: model, conversation: conversation)
                    .frame(maxWidth: 560, maxHeight: .infinity, alignment: .top)
                    .frame(maxWidth: .infinity)
            case .keyProblem:
                KeyProblemView(model: model)
                    .frame(maxWidth: 560, maxHeight: .infinity, alignment: .top)
                    .frame(maxWidth: .infinity)
            case .chat:
                NavigationSplitView {
                    Sidebar(conversation: conversation, state: state)
                        .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 300)
                } detail: {
                    switch state.pane {
                    case .chat: ChatView(model: model, conversation: conversation)
                    case .settings:
                        SettingsView(model: model, conversation: conversation, hotKeyChanged: hotKeyChanged)
                            .navigationTitle("Settings")
                    }
                }
            }
        }
        .frame(minWidth: 760, minHeight: 520)
    }
}

struct Sidebar: View {
    @ObservedObject var conversation: Conversation
    @ObservedObject var state: WindowState

    var body: some View {
        List(selection: $state.selection) {
            Section {
                ForEach(Pane.allCases) { pane in
                    Label(pane.title, systemImage: pane.icon).tag(SidebarItem.pane(pane))
                }
            }
            Section("Today") {
                if conversation.today.isEmpty {
                    Text("No conversations yet today")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                ForEach(conversation.today) { row in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.title)
                            .lineLimit(1)
                            .fontWeight(row.id == conversation.conversationID ? .semibold : .regular)
                        Text("\(row.turns) \(row.turns == 1 ? "turn" : "turns") · \(row.lastAt.formatted(date: .omitted, time: .shortened))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .tag(SidebarItem.conversation(row.id))
                    .help(row.title)
                }
            }
        }
        .listStyle(.sidebar)
        .onChange(of: state.selection) { _, selection in
            guard case .conversation(let id) = selection else { return }
            state.selection = .pane(.chat)
            Task { await conversation.open(id) }
        }
        .onChange(of: conversation.busy) { _, busy in
            if !busy { Task { await conversation.loadToday() } }
        }
        .task { await conversation.loadToday() }
    }
}

/// The window: one per run, kept when closed (Ira goes on working without it), its frame
/// remembered. It follows the person to the Space they are on, a full-screen app's too.
@MainActor
final class MainWindowController: NSObject, NSWindowDelegate {
    let window: NSWindow
    let state = WindowState()
    /// The window was closed: the microphone stops with it.
    var onClose: (() -> Void)?

    init(model: AppModel, hotKeyChanged: @escaping () -> Void) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 980, height: 660),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        super.init()
        window.title = "Ira"
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 760, height: 520)
        window.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
        window.contentView = NSHostingView(rootView: AppWindowView(
            model: model, conversation: model.conversation, state: state, hotKeyChanged: hotKeyChanged))
        window.delegate = self
        if !window.setFrameUsingName(MainWindowController.frameName) { window.center() }
        window.setFrameAutosaveName(MainWindowController.frameName)
    }

    static let frameName = "IraMain"

    var isShown: Bool { window.isVisible && !window.isMiniaturized }

    /// Bring the window forward on [pane]; on Chat, with the Ask field taking the keyboard.
    func show(_ pane: Pane? = nil) {
        if let pane { state.selection = .pane(pane) }
        NSApp.activate(ignoringOtherApps: true)
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
        if state.pane == .chat {
            // After the pane is drawn, so its Ask field is there to take the keyboard.
            DispatchQueue.main.async { NotificationCenter.default.post(name: .iraFocusInput, object: nil) }
        }
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }
}
