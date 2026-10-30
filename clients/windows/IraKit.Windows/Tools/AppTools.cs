using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace IraKit.Tools;

/// <summary>
/// app_open (Tier 1) and url_open (Tier 2) in the <c>apps</c> skill, and clipboard_read
/// (Tier 0) in the <c>clipboard</c> skill.
/// </summary>
internal static class AppTools
{
    public sealed record App(string Name, string Id);

    /// <summary>
    /// Apps Ira never opens: whatever is typed in them runs as a command. Matched by any part of
    /// the name or id, as the server's own list is (erring on the safe side on purpose).
    /// </summary>
    public static readonly string[] NeverApps =
    [
        "terminal", "powershell", "command prompt", "cmd.exe", "registry editor", "regedit",
        "windows subsystem for linux", "wsl", "bash", "git bash", "ubuntu", "debian", "kali",
        "opensuse", "fedora", "alpine", "developer command", "native tools command", "mmc.exe",
        "openconsole", "conhost", "pwsh",
    ];

    public static IEnumerable<DeviceTool> Tools(Func<IReadOnlyList<App>> apps) =>
    [
        new("app_open",
            "Open an app on this PC by its name, as the Start menu shows it (Outlook, Calculator, Visual Studio Code...). "
            + "Say that you opened it. Never a terminal, PowerShell or the Command Prompt.",
            "apps", 1,
            Schema.Object(new JsonObject { ["name"] = Schema.Text("The app's name.") }, "name"),
            (args, ct) => Task.Run(() => Open(args, apps()), ct)),
        new("url_open",
            "Open a web page in the person's browser on this PC. The exact address is read back first.",
            "apps", 2,
            Schema.Object(new JsonObject { ["url"] = Schema.Text("The web address (https://...).") }, "url"),
            (args, ct) => Task.Run(() => OpenUrl(args), ct)),
        new("clipboard_read",
            "Read the text on this PC's clipboard, only when the person asks about what they copied. "
            + "Never what a password manager marked as private.",
            "clipboard", 0, Schema.Object(),
            (args, ct) => Task.Run(() => Clipboard.Read(args), ct)),
    ];

    public static bool IsNever(App app) =>
        NeverApps.Any(word => app.Name.Contains(word, StringComparison.OrdinalIgnoreCase)
            || app.Id.Contains(word, StringComparison.OrdinalIgnoreCase));

    /// <summary>The app a person means: the exact name, else one that starts so, else one that has the words.</summary>
    public static App Pick(string wanted, IReadOnlyList<App> apps)
    {
        wanted = wanted.Trim();
        if (wanted.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) wanted = wanted[..^4];
        var exact = apps.Where(a => a.Name.Equals(wanted, StringComparison.OrdinalIgnoreCase)).ToList();
        var starts = apps.Where(a => a.Name.StartsWith(wanted, StringComparison.OrdinalIgnoreCase)).ToList();
        var words = wanted.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var containing = apps.Where(a => words.All(w => a.Name.Contains(w, StringComparison.OrdinalIgnoreCase))).ToList();
        var candidates = exact.Count > 0 ? exact : starts.Count > 0 ? starts : containing;
        if (candidates.Count == 0) throw new ToolFailure($"there is no app called {wanted} in the Start menu");
        // The same name twice (two installs) is one choice: take the first.
        if (candidates.Select(a => a.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count() > 1)
        {
            var names = candidates.Select(a => a.Name).Distinct(StringComparer.OrdinalIgnoreCase).Order().Take(6);
            throw new ToolFailure($"several apps match {wanted}: {string.Join(", ", names)}. Say which");
        }
        return candidates[0];
    }

    private static JsonNode Open(JsonObject raw, IReadOnlyList<App> apps)
    {
        var args = new ToolArgs(raw, "name");
        var wanted = args.Required("name", 100, "which app (its name)");
        if (IsNever(new App(wanted, ""))) throw new ToolFailure("I never open terminals or shells: whatever is typed there runs as a command");
        var app = Pick(wanted, apps.Where(a => !IsNever(a)).ToList());
        // shell:AppsFolder opens Store apps and installed programs alike, the way Start does.
        var start = new ProcessStartInfo("explorer.exe") { UseShellExecute = false };
        start.ArgumentList.Add($@"shell:AppsFolder\{app.Id}");
        Process.Start(start)?.Dispose();
        return new JsonObject { ["opened"] = app.Name, ["summary"] = $"Opened {app.Name}." };
    }

    /// <summary>An http or https address with a host; null for anything else (file:, javascript:, a bare word).</summary>
    public static Uri? WebUrl(string text)
    {
        text = text.Trim();
        var withScheme = text.Contains("://", StringComparison.Ordinal) ? text : "https://" + text;
        if (!Uri.TryCreate(withScheme, UriKind.Absolute, out var uri)) return null;
        if (uri.Scheme is not ("http" or "https") || uri.Host.Length == 0 || uri.UserInfo.Length > 0) return null;
        return uri;
    }

    private static JsonNode OpenUrl(JsonObject raw)
    {
        var args = new ToolArgs(raw, "url");
        var text = args.Required("url", 2000, "which address (url)");
        var uri = WebUrl(text) ?? throw new ToolFailure("I open only web addresses (http or https)");
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true })?.Dispose();
        return new JsonObject { ["opened"] = uri.Host, ["summary"] = $"Opened {uri.Host} in your browser." };
    }

    /// <summary>The apps the Start menu lists, Store apps included, by name and launch id.</summary>
    public static IReadOnlyList<App> StartMenuApps()
    {
        var apps = new List<App>();
        // The Shell's objects want a single-threaded apartment.
        var thread = new Thread(() =>
        {
            var shellType = Type.GetTypeFromProgID("Shell.Application");
            if (shellType is null) return;
            dynamic? shell = Activator.CreateInstance(shellType);
            if (shell is null) return;
            try
            {
                dynamic folder = shell.NameSpace("shell:AppsFolder");
                foreach (dynamic item in folder.Items())
                {
                    string name = item.Name;
                    string id = item.Path;
                    if (!string.IsNullOrWhiteSpace(name) && !string.IsNullOrWhiteSpace(id)) apps.Add(new App(name, id));
                }
            }
            finally
            {
                Marshal.FinalReleaseComObject(shell);
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join(TimeSpan.FromSeconds(10));
        return apps;
    }
}

/// <summary>The Windows clipboard, read the way Windows' own clipboard history respects privacy.</summary>
internal static class Clipboard
{
    private const uint CF_UNICODETEXT = 13, CF_HDROP = 15, CF_BITMAP = 2, CF_DIB = 8;

    public static JsonNode Read(JsonObject raw)
    {
        _ = new ToolArgs(raw);
        if (!Open()) throw new ToolFailure("another app is using the clipboard right now; ask again in a moment");
        try
        {
            if (IsPrivate()) throw new ToolFailure("the clipboard holds something a password manager marked as private; I do not read it");
            if (IsClipboardFormatAvailable(CF_UNICODETEXT) && Text() is { Length: > 0 } text)
            {
                var cut = FileText.Cut(text, "clipboard", FileTools.MaxText);
                return new JsonObject
                {
                    ["text"] = cut.Text,
                    ["truncated"] = cut.Truncated,
                    ["summary"] = $"The clipboard holds {cut.Text.Length} characters of text.",
                };
            }
            if (IsClipboardFormatAvailable(CF_HDROP) && Files() is { Count: > 0 } files)
            {
                return new JsonObject
                {
                    ["files"] = new JsonArray(files.Select(f => (JsonNode)f).ToArray()),
                    ["summary"] = $"The clipboard holds {files.Count} file{(files.Count == 1 ? "" : "s")}: {string.Join(", ", files.Take(5).Select(Path.GetFileName))}.",
                };
            }
            if (IsClipboardFormatAvailable(CF_BITMAP) || IsClipboardFormatAvailable(CF_DIB))
                return new JsonObject { ["summary"] = "The clipboard holds a picture, not text." };
            return new JsonObject { ["summary"] = "The clipboard is empty." };
        }
        finally
        {
            CloseClipboard();
        }
    }

    /// <summary>
    /// Password managers mark what they copy so Windows keeps it out of clipboard history and
    /// cloud sync; Ira honours the same marks.
    /// </summary>
    private static bool IsPrivate()
    {
        if (IsClipboardFormatAvailable(RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"))) return true;
        foreach (var name in new[] { "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard" })
        {
            var format = RegisterClipboardFormatW(name);
            if (IsClipboardFormatAvailable(format) && Dword(format) == 0) return true;
        }
        return false;
    }

    private static bool Open()
    {
        for (var attempt = 0; attempt < 10; attempt++)
        {
            if (OpenClipboard(IntPtr.Zero)) return true;
            Thread.Sleep(50);
        }
        return false;
    }

    private static string? Text()
    {
        var handle = GetClipboardData(CF_UNICODETEXT);
        if (handle == IntPtr.Zero) return null;
        var pointer = GlobalLock(handle);
        try
        {
            return pointer == IntPtr.Zero ? null : Marshal.PtrToStringUni(pointer);
        }
        finally
        {
            GlobalUnlock(handle);
        }
    }

    private static uint? Dword(uint format)
    {
        var handle = GetClipboardData(format);
        if (handle == IntPtr.Zero || GlobalSize(handle) < 4) return null;
        var pointer = GlobalLock(handle);
        try
        {
            return pointer == IntPtr.Zero ? null : (uint)Marshal.ReadInt32(pointer);
        }
        finally
        {
            GlobalUnlock(handle);
        }
    }

    private static List<string> Files()
    {
        var drop = GetClipboardData(CF_HDROP);
        var files = new List<string>();
        if (drop == IntPtr.Zero) return files;
        var count = DragQueryFileW(drop, 0xFFFFFFFF, null, 0);
        for (uint i = 0; i < Math.Min(count, 50); i++)
        {
            var length = DragQueryFileW(drop, i, null, 0);
            var buffer = new char[length + 1];
            DragQueryFileW(drop, i, buffer, (uint)buffer.Length);
            files.Add(new string(buffer, 0, (int)length));
        }
        return files;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool OpenClipboard(IntPtr owner);

    [DllImport("user32.dll")]
    private static extern bool CloseClipboard();

    [DllImport("user32.dll")]
    private static extern bool IsClipboardFormatAvailable(uint format);

    [DllImport("user32.dll")]
    private static extern IntPtr GetClipboardData(uint format);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern uint RegisterClipboardFormatW(string name);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GlobalLock(IntPtr handle);

    [DllImport("kernel32.dll")]
    private static extern bool GlobalUnlock(IntPtr handle);

    [DllImport("kernel32.dll")]
    private static extern UIntPtr GlobalSize(IntPtr handle);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern uint DragQueryFileW(IntPtr drop, uint index, [Out] char[]? file, uint length);
}
