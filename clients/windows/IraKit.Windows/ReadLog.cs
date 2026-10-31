using System.Text.Json.Nodes;

namespace IraKit;

/// <summary>One thing Ira used on this PC, for the "What I read" list: never what it read.</summary>
public sealed record ReadEntry(DateTimeOffset At, string Tool, string Target, bool Ok)
{
    /// <summary>What the tool did, in words.</summary>
    public string Verb => Tool switch
    {
        "files_find" => "Looked for files",
        "file_read" => "Read a file",
        "file_open" => "Opened a file",
        "screen_read" => "Read your screen",
        "browser_tabs" => "Listed your browser tabs",
        "browser_show_tab" => "Switched to a tab",
        "app_open" => "Opened an app",
        "url_open" => "Opened a web page",
        "clipboard_read" => "Read the clipboard",
        "pc_type" => "Typed on your PC",
        "pc_keys" => "Pressed keys",
        "pc_click" => "Clicked",
        "pc_scroll" => "Scrolled",
        _ => Tool,
    };

    /// <summary>One line: "Read a file: ~\Downloads\plan.pdf", and "(did not run)" when it failed.</summary>
    public string Line => (Target.Length == 0 ? Verb : $"{Verb}: {Target}") + (Ok ? "" : " (did not run)");
}

/// <summary>
/// The last calls Ira made on this PC, newest first, kept in memory only and cleared when Ira
/// quits: what was used and where (a path, a search, an app's name), never the text it read.
/// </summary>
public sealed class ReadLog
{
    public const int Keep = 100;

    private readonly Lock _lock = new();
    private readonly LinkedList<ReadEntry> _entries = new();

    /// <summary>Something was added or the list cleared; raised on the caller's thread.</summary>
    public event Action? Changed;

    public IReadOnlyList<ReadEntry> Entries
    {
        get { lock (_lock) return [.. _entries]; }
    }

    public void Add(ReadEntry entry)
    {
        lock (_lock)
        {
            _entries.AddFirst(entry);
            while (_entries.Count > Keep) _entries.RemoveLast();
        }
        Changed?.Invoke();
    }

    public void Clear()
    {
        lock (_lock) _entries.Clear();
        Changed?.Invoke();
    }

    /// <summary>
    /// What the list shows for a call: a path, a search, a browser or an app, from the call's
    /// arguments (or, for the screen, the program read from its result), never contents.
    /// </summary>
    public static string Target(string tool, JsonObject args, JsonNode? result = null, string? home = null)
    {
        string? Text(string key, int limit = 120) =>
            args[key] is JsonValue value && value.TryGetValue(out string? text) && text.Trim().Length > 0
                ? Cut(text.Trim(), limit)
                : null;

        // The app it acted in: from the result (the program), else as the call named it.
        string In() => (result?["app"] is JsonValue app && app.TryGetValue(out string? program) ? program : Text("app")) is { } where
            ? $" in {where}"
            : "";

        return tool switch
        {
            "files_find" => Search(args, Text),
            "file_read" or "file_open" => Shown(Text("path", 1000), home),
            "screen_read" => result?["app"] is JsonValue app && app.TryGetValue(out string? name) ? Cut(name, 120) : "",
            "browser_tabs" => Text("browser") ?? "all browsers",
            "browser_show_tab" => Text("match") ?? Text("id") ?? "",
            "app_open" => Text("name") ?? "",
            "pc_type" => $"{(args["text"] is JsonValue typed && typed.TryGetValue(out string? text) ? text.Length : 0)} characters" + In(),
            "pc_keys" => (Text("keys") ?? "") + In(),
            "pc_click" => (Text("label") is { } label ? $"“{label}”" : "") + In(),
            "pc_scroll" => (Text("direction") ?? "") + In(),
            "url_open" => Text("url", 2000) is { } url && Uri.TryCreate(url.Contains("://") ? url : "https://" + url, UriKind.Absolute, out var uri)
                ? uri.Host
                : "",
            _ => "",
        };
    }

    private static string Search(JsonObject args, Func<string, int, string?> text)
    {
        List<string> parts = [];
        if (text("query", 60) is { } query) parts.Add($"“{query}”");
        if (text("kind", 40) is { } kind) parts.Add(kind);
        if (args["modifiedWithinDays"] is JsonValue days && days.TryGetValue(out int count)) parts.Add($"last {count} days");
        if (text("folder", 80) is { } folder) parts.Add($"in {folder}");
        return parts.Count == 0 ? "recent files" : string.Join(", ", parts);
    }

    /// <summary>A path with the user's folder written as <c>~</c>, as the PC's tools take it.</summary>
    public static string Shown(string? path, string? home = null)
    {
        if (string.IsNullOrEmpty(path)) return "";
        home ??= Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        home = home.TrimEnd('\\', '/');
        return home.Length > 0 && path.StartsWith(home + @"\", StringComparison.OrdinalIgnoreCase)
            ? "~" + path[home.Length..]
            : path;
    }

    private static string Cut(string text, int limit) => text.Length <= limit ? text : text[..(limit - 1)] + "…";
}
