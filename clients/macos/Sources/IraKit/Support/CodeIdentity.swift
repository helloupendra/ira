import Foundation
import Security

/// Which build of Ira this is, as macOS's privacy settings see it: the code's
/// designated requirement. An ad hoc build is its exact hash; a build signed
/// with the local identity is its certificate. When it changes, a permission
/// macOS gave the old build does not carry over, and the app says so.
public enum CodeIdentity {
    /// The running code's designated requirement, as text; "" when unsigned.
    public static let current: String = {
        var code: SecCode?
        guard SecCodeCopySelf([], &code) == errSecSuccess, let code else { return "" }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess, let staticCode else { return "" }
        var requirement: SecRequirement?
        guard SecCodeCopyDesignatedRequirement(staticCode, [], &requirement) == errSecSuccess, let requirement else { return "" }
        var text: CFString?
        guard SecRequirementCopyString(requirement, [], &text) == errSecSuccess, let text else { return "" }
        return text as String
    }()

    /// Whether this build is tied to its exact bytes (ad hoc): each rebuild is a new app to macOS.
    public static var adHoc: Bool { current.hasPrefix("cdhash") || current.isEmpty }
}
