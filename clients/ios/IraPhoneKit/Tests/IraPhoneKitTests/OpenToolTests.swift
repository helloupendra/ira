import Foundation
import Testing
@testable import IraPhoneKit

/// Links opened, as the iPhone would: the app's own link answers false when it is not installed.
final class FakeOpener: @unchecked Sendable {
    private let lock = NSLock()
    private var opened: [String] = []
    let installed: Set<String>

    init(installed: Set<String>) { self.installed = installed }

    func open(_ url: URL) async -> Bool {
        lock.withLock { opened.append(url.absoluteString) }
        return url.scheme == "https" || installed.contains(url.scheme ?? "")
    }

    var tried: [String] { lock.withLock { opened } }
}

@Suite("Opening apps and pages on the iPhone")
struct OpenToolTests {
    @Test func appsAreKnownByNameNeverGuessed() {
        #expect(OpenTool.app("YouTube")?.scheme == "youtube://")
        #expect(OpenTool.app("youtube app")?.name == "YouTube")
        #expect(OpenTool.app("insta")?.name == "Instagram")
        #expect(OpenTool.app("Terminal") == nil)
    }

    @Test func anInstalledAppOpensByItsOwnLinkElseItsPage() async throws {
        let installed = FakeOpener(installed: ["youtube"])
        let result = try await OpenTool.openApp(["name": "YouTube"], foreground: true) { await installed.open($0) }
        #expect(installed.tried == ["youtube://"])
        #expect(result["summary"] == "Opened YouTube on this iPhone.")

        let missing = FakeOpener(installed: [])
        _ = try await OpenTool.openApp(["name": "YouTube"], foreground: true) { await missing.open($0) }
        #expect(missing.tried == ["youtube://", "https://www.youtube.com"])

        let none = FakeOpener(installed: [])
        await #expect(throws: ToolFailure.self) {
            try await OpenTool.openApp(["name": "WhatsApp"], foreground: true) { await none.open($0) }
        }
    }

    @Test func onlyWhileIraIsOnScreenAndOnlyWebPages() async throws {
        let opener = FakeOpener(installed: ["youtube"])
        await #expect(throws: ToolFailure.self) {
            try await OpenTool.openApp(["name": "YouTube"], foreground: false) { await opener.open($0) }
        }
        await #expect(throws: ToolFailure.self) {
            try await OpenTool.openURL(["url": "tel:+15550100"], foreground: true) { await opener.open($0) }
        }
        await #expect(throws: ToolFailure.self) {
            try await OpenTool.openURL(["url": "file:///etc/hosts"], foreground: true) { await opener.open($0) }
        }
        #expect(opener.tried.isEmpty)
        _ = try await OpenTool.openURL(["url": "youtube.com/watch?v=x"], foreground: true) { await opener.open($0) }
        #expect(opener.tried == ["https://youtube.com/watch?v=x"])
    }

    @Test func theToolsAreOfferedWithTheirTiers() {
        #expect(ToolCatalog.spec("app_open")?.tier == 1)
        #expect(ToolCatalog.spec("url_open")?.tier == 2)
        #expect(ToolCatalog.spec("app_open")?.skill == .apps)
        #expect(!Skill.apps.needsPermission)
    }
}
