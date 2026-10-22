// swift-tools-version:6.0
// The part of Ira for iPhone that needs no screen: pairing, the device and live
// voice protocols, asking, the voice detector, the tools and the first-run
// checklist. It builds for iOS and for macOS, so its tests run with `swift test`
// on a Mac that has only the Command Line Tools, and on an iOS simulator in CI.
import PackageDescription

let package = Package(
    name: "IraPhoneKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "IraPhoneKit", targets: ["IraPhoneKit"])
    ],
    targets: [
        .target(name: "IraPhoneKit"),
        .testTarget(name: "IraPhoneKitTests", dependencies: ["IraPhoneKit"]),
    ]
)
