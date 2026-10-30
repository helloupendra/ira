using System.Text.RegularExpressions;

namespace IraKit;

/// <summary>
/// What a person gives this PC to pair it: the link Ira shows
/// (<c>https://ira.example.com/pair#code=ABCDEFGH</c>), or just the code (<c>ABCD-EFGH</c>)
/// with the address typed separately.
/// </summary>
public sealed partial record PairingLink(ServerAddress? Server, string Code)
{
    /// <summary>Finds a pairing link or code in any text, such as whatever is on the clipboard.</summary>
    public static PairingLink? Find(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;

        var link = LinkPattern().Match(text);
        if (link.Success
            && ServerAddress.TryParse(link.Groups["server"].Value, out var server, out _)
            && NormalizeCode(link.Groups["code"].Value) is { } linkCode)
        {
            return new PairingLink(server, linkCode);
        }
        return NormalizeCode(text.Trim()) is { } code ? new PairingLink(null, code) : null;
    }

    /// <summary>"abcd efgh", "ABCDEFGH" or "ABCD-EFGH" become "ABCD-EFGH"; anything else is null.</summary>
    public static string? NormalizeCode(string text)
    {
        var bare = text.Replace("-", "", StringComparison.Ordinal).Replace(" ", "", StringComparison.Ordinal).ToUpperInvariant();
        return CodePattern().IsMatch(bare) ? $"{bare[..4]}-{bare[4..]}" : null;
    }

    [GeneratedRegex(@"(?<server>https?://[^\s#?]+?)/pair/?#code=(?<code>[A-Za-z0-9-]{8,9})", RegexOptions.IgnoreCase)]
    private static partial Regex LinkPattern();

    [GeneratedRegex("^[A-Z0-9]{8}$")]
    private static partial Regex CodePattern();
}
