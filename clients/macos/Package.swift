// swift-tools-version:6.0
// Ira for Mac: a menu-bar app that pairs with your own IRA server as a device.
// Built with Swift Package Manager alone (no Xcode project).
import PackageDescription

let package = Package(
    name: "IraMac",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "IraKit", targets: ["IraKit"]),
    ],
    targets: [
        // Everything that can be tested without a screen: the device protocol,
        // pairing and the tools.
        .target(name: "IraKit"),
        .testTarget(
            name: "IraKitTests",
            dependencies: ["IraKit"],
            resources: [.copy("Fixtures")]
        ),
    ],
    swiftLanguageModes: [.v5]
)
