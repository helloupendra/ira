// swift-tools-version:6.0
// Ira for Mac: a menu-bar app that pairs with your own IRA server as a device.
// Built with Swift Package Manager alone (no Xcode project); scripts/make-app.sh
// turns the release build into Ira.app, a zip and a dmg.
import PackageDescription

let package = Package(
    name: "IraMac",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "Ira", targets: ["Ira"]),
        .library(name: "IraKit", targets: ["IraKit"]),
    ],
    targets: [
        // Everything that can be tested without a screen: the device protocol,
        // pairing, the tools, the voice transports and the voice detector.
        .target(name: "IraKit"),
        // The app itself: menu bar, hotkey, the floating window, audio devices.
        .executableTarget(name: "Ira", dependencies: ["IraKit"]),
        .testTarget(
            name: "IraKitTests",
            dependencies: ["IraKit"],
            resources: [.copy("Fixtures")]
        ),
        // The app's window: editing keys and keyboard focus. Needs a desktop session.
        .testTarget(name: "IraAppTests", dependencies: ["Ira"]),
    ],
    swiftLanguageModes: [.v5]
)
