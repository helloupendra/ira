import CryptoKit
import Foundation
import LocalAuthentication
import Security

/// An approval window: after the person's PIN on a screen-control action, the
/// next control steps on this device run without asking until it ends
/// (docs/security.md, "Approvals"). The device may stop it, never open one.
public struct ApprovalWindow: Equatable, Sendable {
    public let id: String
    public let deviceID: Int
    public let device: String
    public let openedAt: Date
    public let expiresAt: Date
    public let steps: Int

    public init(id: String, deviceID: Int, device: String, openedAt: Date, expiresAt: Date, steps: Int) {
        self.id = id
        self.deviceID = deviceID
        self.device = device
        self.openedAt = openedAt
        self.expiresAt = expiresAt
        self.steps = steps
    }
}

/// `GET /v1/me/approvals`: the person's minutes setting, open windows, and the
/// apps on each device where Ira may tap and type without asking.
public struct ApprovalState: Equatable, Sendable {
    public var minutes: Int
    public var windows: [ApprovalWindow]
    /// Bundle ids (or Android packages) by device id.
    public var trustedApps: [Int: [String]]
}

public enum Approvals {
    public static func parse(_ json: JSONValue) -> ApprovalState {
        let windows = (json["windows"]?.arrayValue ?? []).compactMap { item -> ApprovalWindow? in
            guard let id = item["id"]?.stringValue, let device = item["device_id"]?.intValue,
                let expires = item["expires_at"]?.doubleValue
            else { return nil }
            return ApprovalWindow(
                id: id, deviceID: device, device: item["device"]?.stringValue ?? "",
                openedAt: Date(timeIntervalSince1970: item["opened_at"]?.doubleValue ?? expires),
                expiresAt: Date(timeIntervalSince1970: expires), steps: item["steps"]?.intValue ?? 0)
        }
        var trusted: [Int: [String]] = [:]
        for entry in json["trusted_apps"]?.arrayValue ?? [] {
            guard let device = entry["device_id"]?.intValue else { continue }
            trusted[device] = (entry["apps"]?.arrayValue ?? []).compactMap(\.stringValue)
        }
        return ApprovalState(minutes: json["minutes"]?.intValue ?? 0, windows: windows, trustedApps: trusted)
    }

    /// Where the person adds or removes trusted apps: the web app's Your assistant page
    /// (adding one needs their PIN in a signed-in session).
    public static func manageLink(server: String) -> URL? {
        URL(string: server.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/#panel=assistant")
    }

    /// The line the window and the menu show while one is open.
    public static func banner(remaining: TimeInterval) -> String {
        if remaining < 60 { return "Ira can control this Mac for less than a minute more" }
        let minutes = Int((remaining / 60).rounded(.up))
        return "Ira can control this Mac for \(minutes) more minute\(minutes == 1 ? "" : "s")"
    }

    /// The tools an approval covers (the server decides; this only says when to look).
    public static func covers(_ tool: String) -> Bool {
        tool.hasPrefix("mac_") || ["screen_read", "app_open", "url_open"].contains(tool)
    }
}

// MARK: Approving with Touch ID

/// What a device signs to confirm an action instead of the PIN: the action's
/// id, the SHA-256 of the summary the person was shown, and its expiry.
public enum ApprovalSignature {
    public static func message(actionID: String, summary: String, expiresAt: Int) -> Data {
        let digest = SHA256.hash(data: Data(summary.utf8)).map { String(format: "%02x", $0) }.joined()
        return Data("ira-approve:1\n\(actionID)\n\(digest)\n\(expiresAt)".utf8)
    }

    public static func base64url(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

/// A key that approves for this device: its public half goes to the server once.
public protocol ApprovalSigner: Sendable {
    /// SubjectPublicKeyInfo, DER.
    var publicKey: Data { get }
    /// An ECDSA P-256 signature over SHA-256 of `message`, DER; asks the person first.
    func sign(_ message: Data, reason: String) async throws -> Data
}

/// The approval key in this Mac's Secure Enclave: it never leaves the chip, and
/// signs only after the person's Touch ID (a new fingerprint added later voids it).
/// What is kept (in the Keychain) is an encrypted handle only this Mac can use.
public struct EnclaveApprovalKey: ApprovalSigner {
    public let handle: Data

    public static var available: Bool {
        var error: NSError?
        return SecureEnclave.isAvailable
            && LAContext().canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
    }

    public init(handle: Data) {
        self.handle = handle
    }

    /// A new key, usable only after Touch ID.
    public static func create() throws -> EnclaveApprovalKey {
        var error: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(
            nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, [.privateKeyUsage, .biometryCurrentSet], &error)
        else { throw ToolFailure("this Mac cannot make a Touch ID key") }
        return EnclaveApprovalKey(handle: try SecureEnclave.P256.Signing.PrivateKey(accessControl: access).dataRepresentation)
    }

    public var publicKey: Data {
        (try? SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: handle))?.publicKey.derRepresentation ?? Data()
    }

    public func sign(_ message: Data, reason: String) async throws -> Data {
        let context = LAContext()
        do {
            try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason)
        } catch {
            throw ToolFailure("Touch ID did not approve it")
        }
        let key = try SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: handle, authenticationContext: context)
        return try key.signature(for: message).derRepresentation
    }
}
