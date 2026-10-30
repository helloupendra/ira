using System.Data.OleDb;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

namespace IraKit.Tools;

/// <summary>
/// Finding files with Windows Search (the index the Start menu uses): by name, by what is in
/// them, by kind and by date, inside the folders Ira may use. When the index is off, a short
/// walk of the folders by name instead.
/// </summary>
internal static class FileSearch
{
    public const int MaxResults = 20;

    public sealed record Query(IReadOnlyList<string> Words, string? Kind, int? ModifiedWithinDays, string? Folder);

    public sealed record Found(string Path, string? Kind, long? Size, DateTime? Modified);

    /// <summary>Kinds a person names, as file extensions or Windows Search's own kinds.</summary>
    public static readonly Dictionary<string, (string[] Extensions, string? WindowsKind)> Kinds = new()
    {
        ["pdf"] = (["pdf"], null),
        ["word"] = (["docx", "doc", "rtf", "odt"], null),
        ["document"] = (["pdf", "docx", "doc", "rtf", "odt", "txt", "md"], "document"),
        ["spreadsheet"] = (["xlsx", "xls", "xlsm", "csv", "ods"], null),
        ["presentation"] = (["pptx", "ppt", "odp"], null),
        ["image"] = (["jpg", "jpeg", "png", "gif", "heic", "webp", "bmp", "tif", "tiff"], "picture"),
        ["video"] = (["mp4", "mov", "mkv", "avi", "wmv", "webm"], "video"),
        ["audio"] = (["mp3", "m4a", "wav", "flac", "aac", "ogg", "wma"], "music"),
        ["text"] = (["txt", "md", "markdown", "log", "csv", "json", "xml", "yaml", "yml", "ini", "toml"], null),
        ["folder"] = ([], "folder"),
        ["app"] = (["lnk", "exe"], "program"),
        ["archive"] = (["zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "xz", "cab"], null),
    };

    /// <summary>Up to six words of up to 60 characters, keeping only letters, digits and . - _ ( ).</summary>
    public static IReadOnlyList<string> Words(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return [];
        var cleaned = new string(text.Select(c => char.IsLetterOrDigit(c) || c is '.' or '-' or '_' ? c : ' ').ToArray());
        return cleaned.Split(' ', StringSplitOptions.RemoveEmptyEntries).Take(6).Select(w => w[..Math.Min(w.Length, 60)]).ToList();
    }

    /// <summary>
    /// The Windows Search SQL for a query in some folders. Every value in it is built here from
    /// the cleaned words, a known kind, a number and folder paths, never typed through.
    /// </summary>
    public static string Sql(Query query, IReadOnlyList<string> scopes, DateTime nowUtc, int top)
    {
        var where = new List<string>
        {
            "(" + string.Join(" OR ", scopes.Select(s => $"SCOPE='file:{SqlText(s.Replace('\\', '/'))}'")) + ")",
        };
        foreach (var word in query.Words)
        {
            // In the name, or inside the file. The words hold no quotes: Words() kept none.
            where.Add($"(System.FileName LIKE '%{word}%' OR CONTAINS(*, '\"{word}*\"'))");
        }
        if (query.Kind is { } kind && Kinds.TryGetValue(kind, out var known))
        {
            var options = known.Extensions.Select(e => $"System.FileExtension = '.{e}'").ToList();
            if (known.WindowsKind is { } windowsKind) options.Add($"System.Kind = '{windowsKind}'");
            where.Add("(" + string.Join(" OR ", options) + ")");
        }
        if (query.ModifiedWithinDays is { } days)
        {
            var since = nowUtc.AddDays(-days).ToString("yyyy/MM/dd HH:mm:ss", CultureInfo.InvariantCulture);
            // Changed lately, or arrived lately (a download keeps the date it was made).
            where.Add($"(System.DateModified >= '{since}' OR System.DateCreated >= '{since}')");
        }
        return $"SELECT TOP {top} System.ItemPathDisplay, System.ItemTypeText, System.Size, System.DateModified "
            + $"FROM SystemIndex WHERE {string.Join(" AND ", where)} ORDER BY System.DateModified DESC";
    }

    private static string SqlText(string text) => text.Replace("'", "''");

    /// <summary>The folder a person names (Downloads, Desktop, Documents, or a path) as a path.</summary>
    public static string FolderPath(string folder) => folder.Trim().ToLowerInvariant() switch
    {
        "downloads" => KnownFolder(new Guid("374DE290-123F-4565-9164-39C4925E467B")) ?? @"~\Downloads",
        "desktop" => Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
        "documents" => Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        "pictures" => Environment.GetFolderPath(Environment.SpecialFolder.MyPictures),
        "videos" => Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
        "music" => Environment.GetFolderPath(Environment.SpecialFolder.MyMusic),
        _ => folder.Trim(),
    };

    /// <summary>Runs a query with Windows Search; null when the index cannot be asked.</summary>
    public static List<Found>? Indexed(Query query, IReadOnlyList<string> scopes, PathPolicy policy, CancellationToken ct)
    {
        var sql = Sql(query, scopes, DateTime.UtcNow, top: 100);
        var found = new List<Found>();
        try
        {
            using var connection = new OleDbConnection("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';");
            connection.Open();
            using var command = new OleDbCommand(sql, connection);
            using var reader = command.ExecuteReader();
            while (reader.Read() && found.Count < MaxResults)
            {
                ct.ThrowIfCancellationRequested();
                if (reader.GetValue(0) is not string path || !policy.Allows(path)) continue;
                found.Add(new Found(
                    path,
                    reader.GetValue(1) as string,
                    reader.GetValue(2) is decimal or long or ulong or int ? Convert.ToInt64(reader.GetValue(2), CultureInfo.InvariantCulture) : null,
                    reader.GetValue(3) is DateTime modified ? modified.ToLocalTime() : null));
            }
            return found;
        }
        catch (Exception e) when (e is OleDbException or InvalidOperationException or COMException)
        {
            return null; // Windows Search is off or not installed
        }
    }

    /// <summary>The slow way, by name only: a walk of the folders, two seconds at most, never into denied ones.</summary>
    public static List<Found> Walk(Query query, IReadOnlyList<string> scopes, PathPolicy policy, CancellationToken ct)
    {
        var watch = Stopwatch.StartNew();
        var since = query.ModifiedWithinDays is { } days ? DateTime.Now.AddDays(-days) : (DateTime?)null;
        var extensions = query.Kind is { } kind && Kinds.TryGetValue(kind, out var known) ? known.Extensions : null;
        var folders = query.Kind == "folder";
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.Hidden | FileAttributes.System | FileAttributes.ReparsePoint,
            MaxRecursionDepth = 8,
        };
        var found = new List<Found>();
        foreach (var scope in scopes)
        {
            IEnumerable<FileSystemInfo> entries;
            try
            {
                entries = new DirectoryInfo(scope).EnumerateFileSystemInfos("*", options);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                continue;
            }
            foreach (var entry in entries)
            {
                ct.ThrowIfCancellationRequested();
                if (watch.Elapsed > TimeSpan.FromSeconds(2)) break;
                var isFolder = entry is DirectoryInfo;
                if (folders != isFolder) continue;
                if (!query.Words.All(w => entry.Name.Contains(w, StringComparison.OrdinalIgnoreCase))) continue;
                if (extensions is { Length: > 0 } && !extensions.Contains(entry.Extension.TrimStart('.').ToLowerInvariant())) continue;
                if (since is { } from && entry.LastWriteTime < from && entry.CreationTime < from) continue;
                if (!policy.Allows(entry.FullName)) continue;
                found.Add(new Found(entry.FullName, isFolder ? "Folder" : null, (entry as FileInfo)?.Length, entry.LastWriteTime));
            }
        }
        return found.OrderByDescending(f => f.Modified).Take(MaxResults).ToList();
    }

    private static string? KnownFolder(Guid id)
    {
        if (SHGetKnownFolderPath(id, 0, IntPtr.Zero, out var path) != 0) return null;
        try
        {
            return Marshal.PtrToStringUni(path);
        }
        finally
        {
            Marshal.FreeCoTaskMem(path);
        }
    }

    [DllImport("shell32.dll")]
    private static extern int SHGetKnownFolderPath([MarshalAs(UnmanagedType.LPStruct)] Guid id, uint flags, IntPtr token, out IntPtr path);

    public static string Summary(IReadOnlyList<Found> found, PathPolicy policy, bool byNameOnly)
    {
        var note = byNameOnly ? " Windows Search is off on this PC, so I looked by name only." : "";
        if (found.Count == 0) return "Nothing matched where I could look." + note;
        var names = found.Take(5).Select(f => $"{Path.GetFileName(f.Path)} in {policy.Display(Path.GetDirectoryName(f.Path) ?? "")}");
        var more = found.Count > 5 ? $" and {found.Count - 5} more" : "";
        var text = new StringBuilder($"Found {found.Count} file{(found.Count == 1 ? "" : "s")}: ");
        return text.Append(string.Join("; ", names)).Append(more).Append('.').Append(note).ToString();
    }
}
