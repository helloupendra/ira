using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace IraKit;

/// <summary>One item in the person's Drop (<c>docs/api.md</c>): text, a link or a file.</summary>
public sealed record DropItem(
    long Id,
    string Kind,
    string? Text = null,
    string? Name = null,
    string? Mime = null,
    long? Size = null,
    string? Sha256 = null,
    long? FromDeviceId = null,
    string FromLabel = "",
    string? CreatedAt = null,
    string? ExpiresAt = null)
{
    [JsonIgnore]
    public bool IsFile => Kind == "file";

    /// <summary>A link this PC may open: one http(s) address, nothing else.</summary>
    [JsonIgnore]
    public Uri? Link
    {
        get
        {
            var text = Text?.Trim();
            if (Kind != "link" || string.IsNullOrEmpty(text) || text.Any(char.IsWhiteSpace)) return null;
            return Uri.TryCreate(text, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https" && uri.Host.Length > 0
                ? uri
                : null;
        }
    }

    /// <summary>One line for a menu or a notification: a file's name and size, or the text.</summary>
    [JsonIgnore]
    public string Preview
    {
        get
        {
            var words = string.Join(' ', (Text ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
            var line = IsFile
                ? $"{Drop.SafeName(Name)} ({Drop.SizeText(Size ?? 0)})" + (words.Length == 0 ? "" : $": {words}")
                : words;
            return line.Length <= 200 ? line : line[..199] + "…";
        }
    }

    internal static DropItem? From(JsonNode? node)
    {
        try
        {
            return node?.Deserialize<DropItem>(Json.Options) is { Kind.Length: > 0 } item ? item : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }
}

/// <summary>A change in the Drop, from the device connection: something new, or one deleted.</summary>
public abstract record DropFrame
{
    public sealed record New(DropItem Item) : DropFrame;
    public sealed record Deleted(long Id) : DropFrame;

    internal static DropFrame? From(JsonNode frame) => frame["event"]?.GetValue<string>() switch
    {
        "new" when DropItem.From(frame["item"]) is { } item => new New(item),
        "deleted" when frame["id"] is JsonValue id && id.TryGetValue<long>(out var number) => new Deleted(number),
        _ => null,
    };
}

public static class Drop
{
    public const string Path = "/v1/me/drop";

    /// <summary>Downloads\Ira, where files from Drop go.</summary>
    public static string Folder => System.IO.Path.Combine(Downloads(), "Ira");

    /// <summary>
    /// File kinds Windows' File Explorer acts on just by showing a folder (their icon can point
    /// at another computer, which leaks the person's sign-in). They are saved with ".download"
    /// added, so they stay plain files until the person renames one.
    /// </summary>
    public static readonly HashSet<string> Inert = new(StringComparer.OrdinalIgnoreCase)
    {
        "lnk", "url", "scf", "library-ms", "searchconnector-ms", "settingcontent-ms", "website", "appref-ms",
    };

    private static readonly HashSet<string> Reserved = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    };

    /// <summary>A file name safe to save on Windows: no folders, no characters Windows refuses, never empty.</summary>
    public static string SafeName(string? name)
    {
        var base_ = (name ?? "").Replace('\\', '/').Split('/').LastOrDefault() ?? "";
        var clean = new string(base_.Where(c => c >= 0x20 && c != 0x7F && "<>:\"|?*".IndexOf(c) < 0).ToArray())
            .Trim().TrimEnd('.', ' ').TrimStart('.');
        if (clean.Length == 0) clean = "file";
        if (Reserved.Contains(System.IO.Path.GetFileNameWithoutExtension(clean))) clean = "_" + clean;
        if (clean.Equals("desktop.ini", StringComparison.OrdinalIgnoreCase)) clean = "desktop.ini.download";
        if (Inert.Contains(System.IO.Path.GetExtension(clean).TrimStart('.'))) clean += ".download";
        return clean.Length <= 200 ? clean : clean[..200];
    }

    /// <summary>Where a file goes in a folder: its name, else "plan (2).pdf", "plan (3).pdf", as Explorer does.</summary>
    public static string FreePath(string folder, string name)
    {
        var first = System.IO.Path.Combine(folder, name);
        if (!System.IO.Path.Exists(first)) return first;
        var stem = System.IO.Path.GetFileNameWithoutExtension(name);
        var ext = System.IO.Path.GetExtension(name);
        for (var number = 2; ; number++)
        {
            var candidate = System.IO.Path.Combine(folder, $"{stem} ({number}){ext}");
            if (!System.IO.Path.Exists(candidate)) return candidate;
        }
    }

    public static string SizeText(long bytes) => bytes switch
    {
        < 1024 => $"{bytes} B",
        < 1024 * 1024 => $"{bytes / 1024.0:0.0} KB",
        _ => $"{bytes / 1024.0 / 1024.0:0.0} MB",
    };

    /// <summary>
    /// Marks a saved file as downloaded from the internet (the Mark of the Web), so Windows
    /// checks it with SmartScreen and opens Office files in Protected View, as for any download.
    /// </summary>
    public static void MarkDownloaded(string path, string server)
    {
        try
        {
            File.WriteAllText(path + ":Zone.Identifier", $"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl={server}\r\n");
        }
        catch (IOException)
        {
            // A disk without streams (FAT32, some network drives): Windows treats it as unknown.
        }
    }

    internal static string Sha256Of(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(stream));
    }

    private static string Downloads()
    {
        if (SHGetKnownFolderPath(new Guid("374DE290-123F-4565-9164-39C4925E467B"), 0, IntPtr.Zero, out var path) == 0)
        {
            try
            {
                return System.Runtime.InteropServices.Marshal.PtrToStringUni(path)!;
            }
            finally
            {
                System.Runtime.InteropServices.Marshal.FreeCoTaskMem(path);
            }
        }
        return System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
    }

    [System.Runtime.InteropServices.DllImport("shell32.dll")]
    private static extern int SHGetKnownFolderPath(
        [System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPStruct)] Guid id,
        uint flags, IntPtr token, out IntPtr path);
}

/// <summary>The Drop's HTTP API with this PC's device key: list, send, delete, and save a file.</summary>
public sealed class DropClient(HttpClient http, ServerAddress server, string token)
{
    public string Server => server.ToString();

    public async Task<(IReadOnlyList<DropItem> Items, bool HasMore)> ListAsync(long? afterId = null, int limit = 50, CancellationToken ct = default)
    {
        var route = $"{Drop.Path}?limit={limit}" + (afterId is { } after ? $"&after_id={after}" : "");
        using var response = await SendAsync(new HttpRequestMessage(HttpMethod.Get, server.Api(route)), ct);
        var body = await response.Content.ReadFromJsonAsync<JsonObject>(Json.Options, ct);
        var items = (body?["items"] as JsonArray ?? []).Select(DropItem.From).OfType<DropItem>().ToList();
        return (items, body?["has_more"]?.GetValue<bool>() ?? false);
    }

    public async Task<DropItem> GetAsync(long id, CancellationToken ct = default)
    {
        using var response = await SendAsync(new HttpRequestMessage(HttpMethod.Get, server.Api($"{Drop.Path}/{id}")), ct);
        return await ItemAsync(response, ct);
    }

    public async Task<DropItem> SendTextAsync(string text, CancellationToken ct = default)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, server.Api(Drop.Path)) { Content = JsonContent.Create(new { text }) };
        using var response = await SendAsync(request, ct);
        return await ItemAsync(response, ct);
    }

    /// <summary>Sends a file, read from disk as it goes (never all in memory).</summary>
    public async Task<DropItem> SendFileAsync(string path, string? caption = null, CancellationToken ct = default)
    {
        FileStream file;
        try
        {
            file = File.OpenRead(path);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            throw new IraError($"{System.IO.Path.GetFileName(path)} could not be read");
        }
        await using (file)
        {
            using var form = new MultipartFormDataContent($"ira-{Guid.NewGuid():N}");
            if (!string.IsNullOrWhiteSpace(caption)) form.Add(new StringContent(caption), "text");
            var content = new StreamContent(file, 1024 * 1024);
            content.Headers.ContentType = new MediaTypeHeaderValue(Mime(path));
            form.Add(content, "file", Drop.SafeName(System.IO.Path.GetFileName(path)));
            var request = new HttpRequestMessage(HttpMethod.Post, server.Api(Drop.Path)) { Content = form };
            using var response = await SendAsync(request, ct, TimeSpan.FromMinutes(10));
            return await ItemAsync(response, ct);
        }
    }

    public async Task DeleteAsync(long id, CancellationToken ct = default)
    {
        try
        {
            using var _ = await SendAsync(new HttpRequestMessage(HttpMethod.Delete, server.Api($"{Drop.Path}/{id}")), ct);
        }
        catch (IraError e) when (e.Status == 404)
        {
            // gone already
        }
    }

    /// <summary>
    /// Saves a file into <paramref name="folder"/> (made if needed), checked against its SHA-256
    /// and marked as downloaded. Returns where it went.
    /// </summary>
    public async Task<string> SaveAsync(DropItem item, string folder, CancellationToken ct = default)
    {
        if (!item.IsFile) throw new IraError("that item is not a file");
        var temp = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"ira-drop-{Guid.NewGuid():N}");
        try
        {
            using (var response = await SendAsync(new HttpRequestMessage(HttpMethod.Get, server.Api($"{Drop.Path}/{item.Id}/file")),
                ct, TimeSpan.FromMinutes(10), HttpCompletionOption.ResponseHeadersRead))
            await using (var sink = File.Create(temp))
            {
                await response.Content.CopyToAsync(sink, ct);
            }
            if (item.Sha256 is { } expected && !Drop.Sha256Of(temp).Equals(expected, StringComparison.OrdinalIgnoreCase))
                throw new IraError("the download did not match the file: try again");
            Directory.CreateDirectory(folder);
            var target = Drop.FreePath(folder, Drop.SafeName(item.Name));
            File.Move(temp, target);
            Drop.MarkDownloaded(target, server.ToString());
            return target;
        }
        finally
        {
            File.Delete(temp);
        }
    }

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct,
        TimeSpan? limit = null, HttpCompletionOption option = HttpCompletionOption.ResponseContentRead)
    {
        using (request)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(limit ?? TimeSpan.FromSeconds(60));
            HttpResponseMessage response;
            try
            {
                response = await http.SendAsync(request, option, timeout.Token);
            }
            catch (HttpRequestException e)
            {
                throw new IraError($"Can't reach your Ira at {server.Host}.", e);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                throw new IraError($"Your Ira at {server.Host} took too long to answer.");
            }
            if (response.IsSuccessStatusCode) return response;
            using (response)
            {
                if (response.StatusCode == HttpStatusCode.Unauthorized)
                    throw new DeviceRevokedError("This PC was removed from your Ira. Pair it again to use it.");
                var text = await response.Content.ReadAsStringAsync(ct);
                throw new IraError(Json.ErrorText(text, (int)response.StatusCode)) { Status = (int)response.StatusCode };
            }
        }
    }

    private static async Task<DropItem> ItemAsync(HttpResponseMessage response, CancellationToken ct) =>
        DropItem.From(await response.Content.ReadFromJsonAsync<JsonNode>(Json.Options, ct))
        ?? throw new IraError("the server's answer was not a Drop item");

    /// <summary>A file's type by its extension, as Windows registers it; else plain bytes.</summary>
    private static string Mime(string path)
    {
        using var key = Microsoft.Win32.Registry.ClassesRoot.OpenSubKey(System.IO.Path.GetExtension(path));
        return key?.GetValue("Content Type") as string ?? "application/octet-stream";
    }
}
