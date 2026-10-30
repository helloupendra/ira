using System.Diagnostics;
using System.Globalization;
using System.Text.Json.Nodes;

namespace IraKit.Tools;

/// <summary>
/// files_find (Tier 0), file_read (Tier 0) and file_open (Tier 1), in the <c>files</c> skill:
/// only inside the folders the <see cref="PathPolicy"/> allows, only when the person asks.
/// </summary>
internal sealed class FileTools(Func<PathPolicy> currentPolicy)
{
    /// <summary>The most text a tool hands back, as on the Mac.</summary>
    public const int MaxText = 20_000;

    /// <summary>What file_open never opens: things that run code, install, or point elsewhere when opened.</summary>
    public static readonly HashSet<string> NeverOpen = new(StringComparer.OrdinalIgnoreCase)
    {
        "exe", "com", "bat", "cmd", "ps1", "psm1", "psd1", "ps1xml", "vbs", "vbe", "js", "jse", "wsf",
        "wsh", "wsc", "hta", "scr", "pif", "cpl", "msc", "msi", "msp", "mst", "msix", "msixbundle",
        "appx", "appxbundle", "appinstaller", "application", "appref-ms", "lnk", "url", "website",
        "reg", "inf", "jar", "py", "pyw", "pyc", "rb", "pl", "sh", "settingcontent-ms",
        "library-ms", "search-ms", "searchconnector-ms", "diagcab", "gadget", "xll", "iso", "img",
        "vhd", "vhdx", "chm", "theme", "themepack", "deskthemepack", "ws", "sct", "dll", "sys",
    };

    public IEnumerable<DeviceTool> Tools() =>
    [
        new("files_find",
            "Find files on this PC with Windows Search, by words in the name or inside the file, by kind and by date. "
            + "Returns up to 20: name, folder, path, kind, size and when it was last changed, newest first. "
            + "Use it for 'where is that file', 'the PDF I downloaded yesterday'.",
            "files", 0,
            Schema.Object(new JsonObject
            {
                ["query"] = Schema.Text("Words from the file's name or its text. Leave empty to list recent files of a kind."),
                ["kind"] = Schema.OneOf("The kind of file.", FileSearch.Kinds.Keys.Order()),
                ["modifiedWithinDays"] = Schema.Integer("Only files changed or added in the last this many days (1 means the last 24 hours).", 1, 3650),
                ["folder"] = Schema.Text(@"Look only in this folder: Downloads, Desktop, Documents, or a path such as ~\Projects."),
            }),
            (args, ct) => Task.Run(() => Find(args, ct), ct)),
        new("file_read",
            "Read the text of one file on this PC: PDF, Word (.docx), RTF, plain text or Markdown, up to 20,000 characters. "
            + "Give the full path from files_find. Never AppData, key files or hidden files.",
            "files", 0,
            Schema.Object(new JsonObject
            {
                ["path"] = Schema.Text(@"The file's full path, e.g. C:\Users\you\Downloads\invoice.pdf or ~\Downloads\invoice.pdf."),
                ["maxChars"] = Schema.Integer("Read at most this many characters (default and most: 20,000).", 200, MaxText),
            }, "path"),
            (args, ct) => Task.Run(() => Read(args), ct)),
        new("file_open",
            "Open a file on this PC in its usual app, or a folder in File Explorer, or a folder or file in VS Code (app: vscode), "
            + "e.g. a repository. Say that you opened it. Never runs programs, scripts or installers.",
            "files", 1,
            Schema.Object(new JsonObject
            {
                ["path"] = Schema.Text(@"The file's or folder's full path, e.g. ~\code\shop."),
                ["app"] = Schema.OneOf("Where to open it: its usual app (default) or VS Code.", ["default", "vscode"]),
            }, "path"),
            (args, ct) => Task.Run(() => Open(args), ct)),
    ];

    // files_find

    private JsonNode Find(JsonObject raw, CancellationToken ct)
    {
        var args = new ToolArgs(raw, "query", "kind", "modifiedWithinDays", "folder");
        var policy = currentPolicy();
        var kind = args.Text("kind")?.ToLowerInvariant();
        if (kind is not null && !FileSearch.Kinds.ContainsKey(kind))
            throw new ToolFailure($"kind must be one of: {string.Join(", ", FileSearch.Kinds.Keys.Order())}");
        var query = new FileSearch.Query(
            FileSearch.Words(args.Text("query", 200)), kind, args.Number("modifiedWithinDays", 1, 3650), args.Text("folder"));

        var scopes = policy.Roots;
        if (query.Folder is { } folder)
        {
            var path = FileSearch.FolderPath(folder);
            if (policy.Refusal(path) is { } refusal) throw new ToolFailure(refusal);
            scopes = [PathPolicy.Resolve(policy.Expand(path)!)];
        }

        var found = FileSearch.Indexed(query, scopes, policy, ct);
        var byNameOnly = found is null;
        found ??= FileSearch.Walk(query, scopes, policy, ct);

        var results = new JsonArray();
        foreach (var file in found)
        {
            var entry = new JsonObject
            {
                ["name"] = Path.GetFileName(file.Path),
                ["folder"] = policy.Display(Path.GetDirectoryName(file.Path) ?? ""),
                ["path"] = file.Path,
            };
            if (file.Kind is { } fileKind) entry["kind"] = fileKind;
            if (file.Size is { } size)
            {
                entry["size"] = size;
                entry["sizeText"] = SizeText(size);
            }
            if (file.Modified is { } modified) entry["modified"] = modified.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture);
            results.Add(entry);
        }
        return new JsonObject
        {
            ["results"] = results,
            ["count"] = found.Count,
            ["summary"] = FileSearch.Summary(found, policy, byNameOnly),
        };
    }

    // file_read

    private JsonNode Read(JsonObject raw)
    {
        var args = new ToolArgs(raw, "path", "maxChars");
        var path = args.Required("path", 2000, "which file: its path");
        var policy = currentPolicy();
        if (policy.Refusal(path) is { } refusal) throw new ToolFailure(refusal);
        var maxChars = args.Number("maxChars", 200, MaxText) ?? MaxText;
        // Read where the path really leads: the policy checked that place.
        var real = PathPolicy.Resolve(policy.Expand(path)!);
        var read = FileText.ReadFile(real, maxChars);
        var name = Path.GetFileName(real);
        var content = new JsonObject
        {
            ["name"] = name,
            ["path"] = real,
            ["kind"] = read.Kind,
            ["chars"] = read.Text.Length,
            ["truncated"] = read.Truncated,
            ["text"] = read.Text,
        };
        if (read.Pages is { } pages) content["pages"] = pages;
        var cut = read.Truncated ? $", the first {read.Text.Length} characters" : "";
        content["summary"] = $"Read {name} ({read.Kind}{cut}).";
        return content;
    }

    // file_open

    /// <summary>Why a path may not be opened, or null.</summary>
    public static string? OpenRefusal(string path, PathPolicy policy)
    {
        if (policy.Refusal(path) is { } refusal) return refusal;
        var real = PathPolicy.Resolve(policy.Expand(path)!);
        if (NeverOpen.Contains(Path.GetExtension(real).TrimStart('.').TrimEnd('.', ' ')))
            return "I never open programs, scripts, installers or links: they could run something";
        return null;
    }

    private JsonNode Open(JsonObject raw)
    {
        var args = new ToolArgs(raw, "path", "app");
        var app = args.Text("app") ?? "default";
        if (app is not ("default" or "vscode")) throw new ToolFailure("app must be default or vscode");
        var path = args.Required("path", 2000, "which file: its path");
        var policy = currentPolicy();
        if (OpenRefusal(path, policy) is { } refusal) throw new ToolFailure(refusal);
        var real = PathPolicy.Resolve(policy.Expand(path)!);
        if (!Path.Exists(real)) throw new ToolFailure("there is nothing at that path");

        if (app == "vscode")
        {
            var code = VsCode() ?? throw new ToolFailure("VS Code isn't installed on this PC");
            var start = new ProcessStartInfo(code) { UseShellExecute = false };
            start.ArgumentList.Add(real);
            Process.Start(start)?.Dispose();
            return new JsonObject { ["opened"] = real, ["summary"] = $"Opened {Path.GetFileName(real)} in VS Code." };
        }
        try
        {
            // A folder opens in File Explorer; a file in the app Windows has for its kind.
            Process.Start(new ProcessStartInfo(real) { UseShellExecute = true })?.Dispose();
        }
        catch (System.ComponentModel.Win32Exception)
        {
            throw new ToolFailure("Windows has no app set up to open that kind of file");
        }
        return new JsonObject { ["opened"] = real, ["summary"] = $"Opened {Path.GetFileName(real)}." };
    }

    /// <summary>VS Code's program, installed for this user or for everyone.</summary>
    internal static string? VsCode() => new[]
    {
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Programs\Microsoft VS Code\Code.exe"),
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Microsoft VS Code\Code.exe"),
    }.FirstOrDefault(File.Exists);

    internal static string SizeText(long bytes) => bytes switch
    {
        < 1024 => $"{bytes} bytes",
        < 1024 * 1024 => $"{bytes / 1024.0:0.#} KB",
        < 1024L * 1024 * 1024 => $"{bytes / (1024.0 * 1024):0.#} MB",
        _ => $"{bytes / (1024.0 * 1024 * 1024):0.##} GB",
    };
}
