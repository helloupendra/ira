import Foundation

/// Masks what looks like a key, a token or a password in text that leaves this Mac or
/// goes into its log: private key blocks, the token shapes of common services, Ira's own
/// tokens, `password=…` style settings, query strings, and long random-looking strings.
///
/// It errs on the side of hiding: a summary that loses an odd word is better than one
/// that carries a key. It is a net, not a guarantee; what it reads is still summarised
/// and cut short before it leaves.
public enum SecretFilter {
    static let rules: [(String, String)] = [
        (#"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"#, "[private key]"),
        // A URL's query and fragment often carry tokens.
        (#"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s?#"'<>]*)[?#][^\s"'<>]*"#, "$1"),
        // user:password@ in an address.
        (#"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/:@"'<>]+:[^\s/@"'<>]+@"#, "$1***@"),
        (#"\birad_[A-Za-z0-9_-]+"#, "irad_***"),
        (#"\bira_[st]_[A-Za-z0-9_-]+"#, "ira_*_***"),
        (#"\b(AKIA|ASIA)[A-Z0-9]{16}\b"#, "[key]"),
        (#"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"#, "[key]"),
        (#"\bsk-[A-Za-z0-9_-]{16,}"#, "[key]"),
        (#"\b[rs]k_(live|test)_[A-Za-z0-9]{10,}"#, "[key]"),
        (#"\bxox[abprs]-[A-Za-z0-9-]{10,}"#, "[key]"),
        (#"\bAIza[0-9A-Za-z_-]{30,}"#, "[key]"),
        (#"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"#, "[token]"),
        (#"(?i)(bearer\s+)\S+"#, "$1***"),
        (#"(?i)(code=)[A-Za-z0-9-]+"#, "$1***"),
        // password: …, api_key=…, "secret": "…", TOKEN=… (the name stays, the value goes).
        (#"(?i)\b((?:[a-z0-9]+[_-])*(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|credentials?|pin)"?\s*[:=]\s*"?)[^\s"',;}]{3,}"#, "$1***"),
    ]

    /// Long strings mixing upper and lower case letters and digits: likely random keys.
    static let opaque = #"[A-Za-z0-9+/_=-]{32,}"#

    public static func mask(_ text: String) -> String {
        var out = text
        for (pattern, template) in rules {
            out = out.replacingOccurrences(of: pattern, with: template, options: .regularExpression)
        }
        return maskOpaque(out)
    }

    static func maskOpaque(_ text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: opaque) else { return text }
        var out = text
        let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
        for match in matches.reversed() {
            guard let range = Range(match.range, in: out) else { continue }
            let word = out[range]
            // A path or a name with dashes is not a key; a hex hash (a commit) is not a secret.
            let upper = word.contains(where: \.isUppercase)
            let lower = word.contains(where: \.isLowercase)
            let digit = word.contains(where: \.isNumber)
            if upper && lower && digit && !word.contains("/") {
                out.replaceSubrange(range, with: "[hidden]")
            }
        }
        return out
    }
}
