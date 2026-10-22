import AppKit

// Ira for Mac: a menu-bar app (LSUIElement), so no Dock icon and no main menu.
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    withExtendedLifetime(delegate) {
        app.run()
    }
}
