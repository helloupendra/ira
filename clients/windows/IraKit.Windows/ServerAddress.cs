namespace IraKit;

/// <summary>
/// The address of a person's own Ira. Plain http is allowed only to this PC itself, so a
/// device key never crosses a network unencrypted.
/// </summary>
public sealed record ServerAddress
{
    public Uri BaseUri { get; }

    private ServerAddress(Uri baseUri) => BaseUri = baseUri;

    /// <summary>The host as people know it, for "Connected to ira.example.com".</summary>
    public string Host => BaseUri.IsDefaultPort ? BaseUri.Host : $"{BaseUri.Host}:{BaseUri.Port}";

    public static ServerAddress Parse(string text)
    {
        if (!TryParse(text, out var server, out var problem)) throw new FormatException(problem);
        return server!;
    }

    public static bool TryParse(string? text, out ServerAddress? server, out string problem)
    {
        server = null;
        text = text?.Trim() ?? "";
        if (text.Length == 0)
        {
            problem = "Type your Ira's address, for example https://ira.example.com";
            return false;
        }
        if (!text.Contains("://", StringComparison.Ordinal)) text = "https://" + text;
        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri) || string.IsNullOrEmpty(uri.Host))
        {
            problem = "That is not a web address.";
            return false;
        }
        if (uri.Scheme == Uri.UriSchemeHttp && !uri.IsLoopback)
        {
            problem = "Your Ira must use https (only an Ira on this PC may use http).";
            return false;
        }
        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
        {
            problem = "The address must start with https://";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query))
        {
            problem = "Use just your Ira's address, without a name, password or ?…";
            return false;
        }
        // Keep a path prefix (an Ira behind /ira/), drop the fragment and the trailing slash.
        var path = uri.AbsolutePath.TrimEnd('/');
        server = new ServerAddress(new UriBuilder(uri.Scheme, uri.Host, uri.Port, path).Uri);
        problem = "";
        return true;
    }

    /// <summary>An API route, such as <c>/v1/devices/pair</c>.</summary>
    public Uri Api(string route) => new(BaseUri.AbsoluteUri.TrimEnd('/') + route);

    /// <summary>The WebSocket form of a route: wss:// for https, ws:// for this PC's own Ira.</summary>
    public Uri WebSocket(string route)
    {
        var builder = new UriBuilder(Api(route))
        {
            Scheme = BaseUri.Scheme == Uri.UriSchemeHttps ? "wss" : "ws",
        };
        return builder.Uri;
    }

    public override string ToString() => BaseUri.AbsoluteUri.TrimEnd('/');
}
