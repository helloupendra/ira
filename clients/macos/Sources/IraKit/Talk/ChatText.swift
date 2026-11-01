import Foundation

/// Ira's answer as the chat shows it: the markdown a model writes (bold, italics, inline code,
/// lists, line breaks) shown as such, never as stars and backticks; and never a link to click,
/// since the model wrote it and a link can lead anywhere.
public enum ChatText {
    public static func attributed(_ text: String) -> AttributedString {
        var options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        options.failurePolicy = .returnPartiallyParsedIfPossible
        guard var shown = try? AttributedString(markdown: bullets(text), options: options) else {
            return AttributedString(text)
        }
        let linked = shown.runs.filter { $0.link != nil || $0.imageURL != nil }.map(\.range)
        for range in linked {
            shown[range].link = nil
            shown[range].imageURL = nil
        }
        return shown
    }

    /// A list item ("- item", "* item", "+ item") starts with a bullet instead.
    static func bullets(_ text: String) -> String {
        text.replacingOccurrences(of: #"(?m)^(\s*)[-*+]\s+"#, with: "$1• ", options: .regularExpression)
    }
}
