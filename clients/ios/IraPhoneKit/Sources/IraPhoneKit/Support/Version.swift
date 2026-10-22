import Foundation

public enum IraPhone {
    /// This app's version; project.yml gives the app the same.
    public static let version = "0.1.0"
    /// Sent with every request, so the server can tell the iPhone app apart.
    public static let userAgent = "ira-ios/\(version)"
    /// The device kind this app pairs as.
    public static let deviceKind = "ios"
    /// Where the app keeps its key in the Keychain, and its log category.
    public static let bundleID = "io.github.helloupendra.ira"
}
