import Foundation

/// `app_open` (Tier 1) and `url_open` (Tier 2), the "apps" skill: an app or a web page opened
/// on this iPhone. iOS lets an app open another only while it is on screen, and only by a
/// link: an app's own (`youtube://`) or its web address, which opens the app when it is
/// installed and the browser when not. So apps are known by name here, never guessed.
public enum OpenTool {
    public struct App: Sendable, Equatable {
        public let name: String
        /// Other names people say for it.
        public let also: [String]
        /// The app's own link, tried first.
        public let scheme: String?
        /// Its web address: the app when installed, else the browser.
        public let web: String?
    }

    public static let apps: [App] = [
        App(name: "YouTube", also: ["yt"], scheme: "youtube://", web: "https://www.youtube.com"),
        App(name: "YouTube Music", also: ["yt music"], scheme: "youtubemusic://", web: "https://music.youtube.com"),
        App(name: "WhatsApp", also: ["whats app"], scheme: "whatsapp://", web: nil),
        App(name: "Instagram", also: ["insta"], scheme: "instagram://", web: "https://www.instagram.com"),
        App(name: "Spotify", also: [], scheme: "spotify://", web: "https://open.spotify.com"),
        App(name: "Telegram", also: [], scheme: "tg://", web: nil),
        App(name: "Gmail", also: [], scheme: "googlegmail://", web: "https://mail.google.com"),
        App(name: "Google Maps", also: [], scheme: "comgooglemaps://", web: "https://maps.google.com"),
        App(name: "Chrome", also: ["google chrome"], scheme: "googlechrome://", web: nil),
        App(name: "Netflix", also: [], scheme: "nflx://", web: "https://www.netflix.com"),
        App(name: "Maps", also: ["apple maps"], scheme: "maps://", web: nil),
        App(name: "Music", also: ["apple music"], scheme: "music://", web: nil),
        App(name: "Mail", also: ["apple mail"], scheme: "message://", web: nil),
        App(name: "Calendar", also: [], scheme: "calshow://", web: nil),
        App(name: "Notes", also: [], scheme: "mobilenotes://", web: nil),
        App(name: "Photos", also: ["gallery"], scheme: "photos-redirect://", web: nil),
        App(name: "Podcasts", also: [], scheme: "podcasts://", web: nil),
    ]

    /// The app a person means: the name or another name for it, any case, "app" left out.
    public static func app(_ said: String) -> App? {
        let wanted = said.lowercased().replacingOccurrences(of: " app", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        return apps.first { $0.name.lowercased() == wanted || $0.also.contains(wanted) }
    }

    /// A web page Ira may open: http or https, with a host. Nothing else (no app's own links,
    /// no `tel:`, no `file:`): those would do what the person never read back.
    public static func webAddress(_ raw: String) throws -> URL {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let address = text.contains("://") ? text : "https://" + text
        guard let url = URL(string: address), let scheme = url.scheme?.lowercased(), ["http", "https"].contains(scheme),
            let host = url.host, !host.isEmpty, !text.contains(where: \.isWhitespace)
        else {
            throw ToolFailure("give a web address (https://...); Ira opens only web pages")
        }
        return url
    }

    public static func openApp(
        _ raw: JSONValue, foreground: Bool, open: @Sendable (URL) async -> Bool
    ) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["name"])
        let name = try args.required("name", limit: 60, what: "which app to open (name)")
        guard let app = app(name) else {
            throw ToolFailure("Ira can open these apps on the iPhone: \(apps.map(\.name).joined(separator: ", ")). For anything else, open its web page")
        }
        guard foreground else {
            throw ToolFailure("open Ira on the iPhone's screen first: iOS lets only the app in front open another")
        }
        for link in [app.scheme, app.web].compactMap({ $0 }) {
            if let url = URL(string: link), await open(url) {
                return ["app": .string(app.name), "summary": .string("Opened \(app.name) on this iPhone.")]
            }
        }
        throw ToolFailure("\(app.name) is not on this iPhone")
    }

    public static func openURL(
        _ raw: JSONValue, foreground: Bool, open: @Sendable (URL) async -> Bool
    ) async throws -> JSONValue {
        let args = try ToolArgs(raw, allowed: ["url"])
        let url = try webAddress(try args.required("url", limit: 2000, what: "the web address (url)"))
        guard foreground else {
            throw ToolFailure("open Ira on the iPhone's screen first: iOS lets only the app in front open a page")
        }
        guard await open(url) else { throw ToolFailure("the iPhone could not open that page") }
        return ["url": .string(url.absoluteString), "summary": .string("Opened \(url.host ?? "the page") on this iPhone.")]
    }
}
