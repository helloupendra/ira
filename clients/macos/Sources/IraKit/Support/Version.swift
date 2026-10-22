import Foundation

public enum IraApp {
    /// This app's version; make-app.sh writes the same into Info.plist.
    public static let version = "0.2.2"
    /// Sent with every request, as the Python companion sends `ira-mac/<version>`.
    public static let userAgent = "ira-mac-app/\(version)"
    /// The device kind this app pairs as.
    public static let deviceKind = "mac"
}
