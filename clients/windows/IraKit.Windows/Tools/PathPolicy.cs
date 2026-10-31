using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace IraKit.Tools;

/// <summary>
/// Which files Ira may find, read and open on this PC (the Mac's rules, in Windows terms).
/// <list type="bullet">
/// <item>Only inside the allowed folders: the user's folder by default, narrowed to chosen
/// folders if the person picks some, plus any folders elsewhere they add.</item>
/// <item>Never the deny list, wherever it is: <c>AppData</c> (browser profiles, saved
/// passwords, mail), credential folders such as <c>.ssh</c> and <c>.aws</c>, key files, and any
/// hidden or system file or folder.</item>
/// <item>Links, junctions and short (8.3) names are resolved first, so a junction on the Desktop
/// to <c>AppData</c> is refused like <c>AppData</c> itself. Network paths, device paths and
/// alternate data streams are refused outright.</item>
/// </list>
/// </summary>
public sealed class PathPolicy
{
    /// <summary>Folders in the user's folder that are never read, listed or opened.</summary>
    public static readonly string[] DeniedHomeFolders =
    [
        "AppData", ".ssh", ".aws", ".gnupg", ".gpg", ".config", ".kube", ".docker", ".azure",
        ".gcloud", ".terraform.d", ".password-store", ".local", ".cache", "NTUSER.DAT",
    ];

    /// <summary>File names that are never read, wherever they are.</summary>
    public static readonly HashSet<string> DeniedNames = new(StringComparer.OrdinalIgnoreCase)
    {
        ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".vault-token", ".pgpass",
        ".my.cnf", ".zsh_history", ".bash_history", ".python_history", ".env", "id_rsa", "id_dsa",
        "id_ecdsa", "id_ed25519", "credentials", "known_hosts", "authorized_keys",
        "ConsoleHost_history.txt",
    };

    /// <summary>File extensions that hold keys, password vaults or saved sign-ins.</summary>
    public static readonly HashSet<string> DeniedExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "pem", "key", "p12", "pfx", "kdbx", "kdb", "ppk", "gpg", "asc", "jks", "keystore", "ovpn",
        "rdp", "psafe3", "opvault", "1pux", "crd", "sst",
    };

    private readonly string[] _deniedSystemFolders;

    public string Home { get; }
    public IReadOnlyList<string> Roots { get; }

    /// <param name="home">The user's folder.</param>
    /// <param name="only">When not empty, Ira looks only inside these folders.</param>
    /// <param name="extra">Folders outside the user's folder Ira may also use.</param>
    public PathPolicy(string home, IEnumerable<string>? only = null, IEnumerable<string>? extra = null)
    {
        Home = Resolve(Path.GetFullPath(home));
        var chosen = (only ?? []).Select(Expand).OfType<string>().Select(Resolve).ToList();
        var added = (extra ?? []).Select(Expand).OfType<string>().Select(Resolve).ToList();
        Roots = [.. chosen.Count == 0 ? [Home] : chosen, .. added];
        _deniedSystemFolders = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        }.Where(f => f.Length > 0).Select(f => f.TrimEnd('\\')).ToArray();
    }

    public static PathPolicy Current() =>
        new(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));

    /// <summary>
    /// The rules for the folders chosen in Settings: folders inside the user's folder narrow Ira
    /// to them, and folders elsewhere (another drive, say) are added. None: the user's folder.
    /// </summary>
    public static PathPolicy ForFolders(string home, IEnumerable<string> folders)
    {
        var start = new PathPolicy(home);
        var full = folders.Select(start.Expand).OfType<string>().Select(Resolve).ToList();
        return new PathPolicy(home,
            only: full.Where(f => IsInside(f, start.Home)),
            extra: full.Where(f => !IsInside(f, start.Home)));
    }

    /// <summary>
    /// <c>~</c>, <c>~\x</c> or a full path (<c>C:\x</c>) as a full path; null for anything
    /// relative, on the network or otherwise odd.
    /// </summary>
    public string? Expand(string path)
    {
        path = path.Trim().Trim('"');
        if (path.Length == 0) return null;
        if (path == "~") return Home;
        if (path.StartsWith("~/", StringComparison.Ordinal) || path.StartsWith(@"~\", StringComparison.Ordinal))
            path = Path.Combine(Home, path[2..]);
        // A drive and a folder (C:\...), nothing else: not \\server\share, \\?\, \\.\ or C:file.
        if (path.Length < 3 || !char.IsAsciiLetter(path[0]) || path[1] != ':' || path[2] is not ('\\' or '/'))
            return null;
        // A colon after the drive names an alternate data stream; * and ? are wildcards.
        if (path.IndexOf(':', 2) >= 0 || path.IndexOfAny(['*', '?', '"', '<', '>', '|']) >= 0) return null;
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception e) when (e is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return null;
        }
    }

    /// <summary>Why a path may not be used, or null when it may.</summary>
    public string? Refusal(string path)
    {
        if (Expand(path) is not { } written) return @"give the full path, such as C:\Users\you\Downloads\file.pdf or ~\Downloads\file.pdf";
        var real = Resolve(written);
        if (real.StartsWith(@"\\", StringComparison.Ordinal)) return "Ira never reads network folders";
        // The path as written and where its links lead: both must pass.
        foreach (var candidate in new[] { written, real })
        {
            if (DeniedReason(candidate) is { } reason) return reason;
        }
        if (!Roots.Any(root => IsInside(real, root))) return "that is outside the folders Ira may use on this PC";
        return null;
    }

    public bool Allows(string path) => Refusal(path) is null;

    private string? DeniedReason(string path)
    {
        var inHome = IsInside(path, Home);
        if (!inHome && _deniedSystemFolders.Any(folder => IsInside(path, folder)))
            return "Ira never reads Windows' own folders or installed programs";

        var parts = (inHome ? path[Home.Length..] : path[3..])
            .Split('\\', StringSplitOptions.RemoveEmptyEntries)
            // Windows drops trailing dots and spaces: "key.pem." opens key.pem.
            .Select(part => part.TrimEnd('.', ' '))
            .ToList();
        if (inHome && parts.Count > 0
            && DeniedHomeFolders.FirstOrDefault(d => d.Equals(parts[0], StringComparison.OrdinalIgnoreCase)) is { } denied)
        {
            return $@"Ira never reads ~\{denied}";
        }
        if (parts.Any(p => p.StartsWith('.')) || parts.Any(p => p is "$Recycle.Bin" or "System Volume Information"))
            return "Ira never reads hidden files or folders";
        if (IsHiddenOrSystem(inHome ? Home : path[..3], parts))
            return "Ira never reads hidden files or folders";

        var name = parts.LastOrDefault() ?? "";
        if (DeniedNames.Contains(name) || name.StartsWith(".env", StringComparison.OrdinalIgnoreCase)
            || name.StartsWith("id_rsa", StringComparison.OrdinalIgnoreCase)
            || name.StartsWith("id_ed25519", StringComparison.OrdinalIgnoreCase))
        {
            return "Ira never reads files that hold passwords or keys";
        }
        if (DeniedExtensions.Contains(Path.GetExtension(name).TrimStart('.')))
            return "Ira never reads key or password files";
        return null;
    }

    /// <summary>Whether any existing part of the path below <paramref name="start"/> is hidden or a system file.</summary>
    private static bool IsHiddenOrSystem(string start, List<string> parts)
    {
        var current = start;
        foreach (var part in parts)
        {
            current = Path.Combine(current, part);
            FileAttributes attributes;
            try
            {
                attributes = File.GetAttributes(current);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                return false; // not there (yet): nothing hidden to find further down
            }
            if ((attributes & (FileAttributes.Hidden | FileAttributes.System)) != 0) return true;
        }
        return false;
    }

    public static bool IsInside(string path, string folder)
    {
        path = path.TrimEnd('\\');
        folder = folder.TrimEnd('\\');
        return path.Equals(folder, StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(folder + @"\", StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>A path for people: the user's folder as <c>~</c>.</summary>
    public string Display(string path) =>
        IsInside(path, Home) ? "~" + path[Home.TrimEnd('\\').Length..] : path;

    /// <summary>
    /// The real path as Windows itself names it: links and junctions followed, short names
    /// expanded, letters in their real case. The parts that do not exist yet are kept as given.
    /// </summary>
    internal static string Resolve(string path)
    {
        var existing = path.TrimEnd('\\');
        var rest = new Stack<string>();
        while (!Path.Exists(existing) && Path.GetDirectoryName(existing) is { } parent)
        {
            rest.Push(Path.GetFileName(existing));
            existing = parent.TrimEnd('\\');
        }
        var real = FinalPath(existing.Length == 2 ? existing + @"\" : existing) ?? existing;
        while (rest.Count > 0) real = Path.Combine(real, rest.Pop());
        return real.TrimEnd('\\').Length == 2 ? real : real.TrimEnd('\\');
    }

    private static string? FinalPath(string path)
    {
        using var handle = CreateFileW(path, 0, FileShare.ReadWrite | FileShare.Delete, IntPtr.Zero,
            FileMode.Open, FILE_FLAG_BACKUP_SEMANTICS, IntPtr.Zero);
        if (handle.IsInvalid) return null;
        var buffer = new char[32_768];
        var length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Length, 0);
        if (length == 0 || length >= buffer.Length) return null;
        var final = new string(buffer, 0, (int)length);
        if (final.StartsWith(@"\\?\UNC\", StringComparison.Ordinal)) return @"\\" + final[8..];
        return final.StartsWith(@"\\?\", StringComparison.Ordinal) ? final[4..] : final;
    }

    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string name, uint access, FileShare share, IntPtr security,
        FileMode mode, uint flags, IntPtr template);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, [Out] char[] path, uint length, uint flags);
}
