using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Text;
using System.Text.Json.Nodes;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;

namespace IraKit.Tools;

/// <summary>A top-level window, and the program it belongs to as Ira names apps on Windows.</summary>
public sealed record WindowInfo(IntPtr Handle, string Program, string AppName, string Title, string ClassName)
{
    /// <summary>The window and its program; null when the handle is no longer a window.</summary>
    public static WindowInfo? Of(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero || !Native.IsWindow(hwnd)) return null;
        var path = ProgramPath(hwnd);
        // A Store app's window belongs to ApplicationFrameHost; the app itself is inside it.
        if (path is not null && Path.GetFileName(path).Equals("ApplicationFrameHost.exe", StringComparison.OrdinalIgnoreCase)
            && HostedApp(hwnd) is { } hosted)
        {
            path = hosted;
        }
        var program = path is null ? "" : Path.GetFileName(path).ToLowerInvariant();
        return new WindowInfo(hwnd, program, AppNameOf(path), Native.Text(hwnd), Native.ClassName(hwnd));
    }

    private static string? ProgramPath(IntPtr hwnd)
    {
        Native.GetWindowThreadProcessId(hwnd, out var pid);
        return pid == 0 ? null : Native.ProcessPath(pid);
    }

    private static string? HostedApp(IntPtr frame)
    {
        Native.GetWindowThreadProcessId(frame, out var framePid);
        string? found = null;
        Native.EnumChildWindows(frame, (child, _) =>
        {
            Native.GetWindowThreadProcessId(child, out var pid);
            if (pid != framePid && Native.ProcessPath(pid) is { } path)
            {
                found = path;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    private static string AppNameOf(string? path)
    {
        if (path is null) return "an app";
        try
        {
            var description = FileVersionInfo.GetVersionInfo(path).FileDescription;
            if (!string.IsNullOrWhiteSpace(description)) return description.Trim();
        }
        catch (FileNotFoundException)
        {
        }
        return Path.GetFileNameWithoutExtension(path);
    }
}

/// <summary>
/// screen_read (Tier 0, <c>screen</c> skill): the text of the window the person is in, read on
/// this PC with Windows' own text recognition. Only the words leave the PC, never a picture.
/// </summary>
internal sealed class ScreenTools(Func<IntPtr> targetWindow)
{
    /// <summary>Programs whose windows Ira never reads: they can show passwords.</summary>
    public static readonly Dictionary<string, string> NeverRead = new(StringComparer.OrdinalIgnoreCase)
    {
        ["1password.exe"] = "1Password",
        ["bitwarden.exe"] = "Bitwarden",
        ["keepass.exe"] = "KeePass",
        ["keepassxc.exe"] = "KeePassXC",
        ["lastpass.exe"] = "LastPass",
        ["dashlane.exe"] = "Dashlane",
        ["enpass.exe"] = "Enpass",
        ["roboform.exe"] = "RoboForm",
        ["nordpass.exe"] = "NordPass",
        ["keeperpasswordmanager.exe"] = "Keeper",
        ["proton pass.exe"] = "Proton Pass",
        ["credentialuibroker.exe"] = "the Windows sign-in prompt",
        ["consent.exe"] = "the administrator prompt",
        ["logonui.exe"] = "the sign-in screen",
        ["lockapp.exe"] = "the lock screen",
    };

    /// <summary>Windows' own surfaces: in front, they are not the window the person means.</summary>
    private static readonly HashSet<string> ShellPrograms = new(StringComparer.OrdinalIgnoreCase)
    {
        "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe",
        "shellhost.exe",
    };

    private static readonly HashSet<string> ShellClasses = new(StringComparer.Ordinal)
    {
        "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
    };

    /// <summary>Why the window is not read, or null.</summary>
    public static string? Refusal(WindowInfo window)
    {
        if (NeverRead.TryGetValue(window.Program, out var known))
            return $"I never read {known}'s window: it can show passwords. Bring the window you mean to the front and ask again";
        if (ShellPrograms.Contains(window.Program)
            || window.Program == "explorer.exe" && ShellClasses.Contains(window.ClassName))
        {
            return "Windows' desktop, taskbar or Start is in front. Bring the window you mean to the front and ask again";
        }
        return null;
    }

    public DeviceTool Tool() => new("screen_read",
        "Read the text of the window the person is in on this PC, in any app, only when they ask what is on their screen. "
        + "Returns the app's program, its name, the window's title and the text, read on the PC; no picture is sent.",
        "screen", 0, Schema.Object(), (args, ct) => ReadAsync(args, ct));

    private async Task<JsonNode> ReadAsync(JsonObject raw, CancellationToken ct)
    {
        _ = new ToolArgs(raw);
        var window = WindowInfo.Of(targetWindow()) ?? throw new ToolFailure("no window is open in front");
        if (Refusal(window) is { } refusal) throw new ToolFailure(refusal);
        if (Native.IsIconic(window.Handle)) throw new ToolFailure($"{window.AppName}'s window is minimised; open it and ask again");

        var engine = OcrEngine.TryCreateFromUserProfileLanguages()
            ?? throw new ToolFailure("Windows has no text recognition for this PC's languages; add English in Settings > Time & language");
        using var bitmap = Capture(window.Handle, (int)OcrEngine.MaxImageDimension);
        ct.ThrowIfCancellationRequested();
        var result = await engine.RecognizeAsync(bitmap).AsTask(ct);
        var text = string.Join("\n", result.Lines.Select(line => line.Text));
        var read = FileText.Cut(text, "screen", FileTools.MaxText);

        var target = window.Title.Length == 0 ? window.AppName : $"{window.AppName} — {window.Title}";
        var lines = read.Text.Length == 0 ? 0 : read.Text.Split('\n').Length;
        return new JsonObject
        {
            // The program: the server checks it against the apps Ira never acts in.
            ["app"] = window.Program,
            ["appName"] = window.AppName,
            ["window"] = window.Title,
            ["text"] = read.Text,
            ["chars"] = read.Text.Length,
            ["truncated"] = read.Truncated,
            ["summary"] = read.Text.Length == 0
                ? $"The {target} window shows no text I can read."
                : $"Read the {target} window: {lines} line{(lines == 1 ? "" : "s")} of text.",
        };
    }

    /// <summary>
    /// The window as the app draws it (even where another window covers it), scaled down to
    /// what text recognition takes.
    /// </summary>
    internal static SoftwareBitmap Capture(IntPtr hwnd, int maxDimension)
    {
        if (!Native.GetWindowRect(hwnd, out var rect)) throw new ToolFailure("that window closed");
        var width = rect.Right - rect.Left;
        var height = rect.Bottom - rect.Top;
        if (width < 8 || height < 8) throw new ToolFailure("that window is too small to read");

        var pixels = Native.PrintWindowPixels(hwnd, width, height);
        if (pixels.All(b => b == 0))
            pixels = Native.ScreenPixels(rect.Left, rect.Top, width, height); // some apps draw only to the screen

        var scale = Math.Min(1.0, (double)maxDimension / Math.Max(width, height));
        if (scale < 1.0)
        {
            (pixels, width, height) = Native.Scale(pixels, width, height, scale);
        }
        return SoftwareBitmap.CreateCopyFromBuffer(pixels.AsBuffer(), BitmapPixelFormat.Bgra8, width, height, BitmapAlphaMode.Ignore);
    }
}

/// <summary>The Win32 calls the tools need.</summary>
internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left, Top, Right, Bottom;
    }

    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr data);

    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hwnd, int command);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern bool EnumChildWindows(IntPtr parent, EnumWindowsProc callback, IntPtr data);

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(uint attach, uint to, bool doAttach);

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextW(IntPtr hwnd, StringBuilder text, int max);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassNameW(IntPtr hwnd, StringBuilder text, int max);

    public static string Text(IntPtr hwnd)
    {
        var text = new StringBuilder(512);
        GetWindowTextW(hwnd, text, text.Capacity);
        return text.ToString();
    }

    public static string ClassName(IntPtr hwnd)
    {
        var text = new StringBuilder(256);
        GetClassNameW(hwnd, text, text.Capacity);
        return text.ToString();
    }

    /// <summary>Brings a window to the front, even when Ira is not the app in front.</summary>
    public static void BringToFront(IntPtr hwnd)
    {
        if (IsIconic(hwnd)) ShowWindow(hwnd, 9); // SW_RESTORE
        var front = GetForegroundWindow();
        var frontThread = GetWindowThreadProcessId(front, out _);
        var ours = GetCurrentThreadId();
        var attached = frontThread != 0 && frontThread != ours && AttachThreadInput(ours, frontThread, true);
        try
        {
            SetForegroundWindow(hwnd);
        }
        finally
        {
            if (attached) AttachThreadInput(ours, frontThread, false);
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, StringBuilder name, ref uint size);

    /// <summary>A process's program file; null when Windows will not say (a protected process).</summary>
    public static string? ProcessPath(uint pid)
    {
        var process = OpenProcess(0x1000, false, pid); // PROCESS_QUERY_LIMITED_INFORMATION
        if (process == IntPtr.Zero) return null;
        try
        {
            var name = new StringBuilder(1024);
            var size = (uint)name.Capacity;
            return QueryFullProcessImageNameW(process, 0, name, ref size) ? name.ToString() : null;
        }
        finally
        {
            CloseHandle(process);
        }
    }

    // Capturing a window's pixels, as 32-bit BGRA rows from the top.

    [StructLayout(LayoutKind.Sequential)]
    private struct BITMAPINFOHEADER
    {
        public int Size, Width, Height;
        public short Planes, BitCount;
        public int Compression, SizeImage, XPelsPerMeter, YPelsPerMeter, ClrUsed, ClrImportant;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetDC(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern int ReleaseDC(IntPtr hwnd, IntPtr dc);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateCompatibleDC(IntPtr dc);

    [DllImport("gdi32.dll")]
    private static extern bool DeleteDC(IntPtr dc);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateDIBSection(IntPtr dc, ref BITMAPINFOHEADER info, uint usage, out IntPtr bits, IntPtr section, uint offset);

    [DllImport("gdi32.dll")]
    private static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);

    [DllImport("gdi32.dll")]
    private static extern bool DeleteObject(IntPtr obj);

    [DllImport("gdi32.dll")]
    private static extern bool BitBlt(IntPtr dest, int x, int y, int w, int h, IntPtr source, int sx, int sy, uint rop);

    [DllImport("gdi32.dll")]
    private static extern bool StretchBlt(IntPtr dest, int x, int y, int w, int h, IntPtr source, int sx, int sy, int sw, int sh, uint rop);

    [DllImport("gdi32.dll")]
    private static extern int SetStretchBltMode(IntPtr dc, int mode);

    [DllImport("user32.dll")]
    private static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);

    private const uint SRCCOPY = 0x00CC0020;

    /// <summary>Draws into a fresh top-down 32-bit bitmap and returns its pixels.</summary>
    private static byte[] Draw(int width, int height, Action<IntPtr> draw)
    {
        var screen = GetDC(IntPtr.Zero);
        var memory = CreateCompatibleDC(screen);
        var header = new BITMAPINFOHEADER
        {
            Size = Marshal.SizeOf<BITMAPINFOHEADER>(),
            Width = width,
            Height = -height,
            Planes = 1,
            BitCount = 32,
        };
        var bitmap = CreateDIBSection(screen, ref header, 0, out var bits, IntPtr.Zero, 0);
        if (bitmap == IntPtr.Zero)
        {
            DeleteDC(memory);
            ReleaseDC(IntPtr.Zero, screen);
            throw new ToolFailure("there was not enough memory to capture that window");
        }
        var old = SelectObject(memory, bitmap);
        try
        {
            draw(memory);
            var pixels = new byte[width * height * 4];
            Marshal.Copy(bits, pixels, 0, pixels.Length);
            return pixels;
        }
        finally
        {
            SelectObject(memory, old);
            DeleteObject(bitmap);
            DeleteDC(memory);
            ReleaseDC(IntPtr.Zero, screen);
        }
    }

    public static byte[] PrintWindowPixels(IntPtr hwnd, int width, int height) =>
        Draw(width, height, dc => PrintWindow(hwnd, dc, 2)); // PW_RENDERFULLCONTENT

    public static byte[] ScreenPixels(int x, int y, int width, int height) => Draw(width, height, dc =>
    {
        var screen = GetDC(IntPtr.Zero);
        try
        {
            BitBlt(dc, 0, 0, width, height, screen, x, y, SRCCOPY);
        }
        finally
        {
            ReleaseDC(IntPtr.Zero, screen);
        }
    });

    public static (byte[] Pixels, int Width, int Height) Scale(byte[] pixels, int width, int height, double scale)
    {
        var newWidth = Math.Max(1, (int)(width * scale));
        var newHeight = Math.Max(1, (int)(height * scale));
        var scaled = Draw(newWidth, newHeight, dc =>
        {
            var screen = GetDC(IntPtr.Zero);
            var sourceDc = CreateCompatibleDC(screen);
            var header = new BITMAPINFOHEADER
            {
                Size = Marshal.SizeOf<BITMAPINFOHEADER>(),
                Width = width,
                Height = -height,
                Planes = 1,
                BitCount = 32,
            };
            var bitmap = CreateDIBSection(screen, ref header, 0, out var bits, IntPtr.Zero, 0);
            var old = SelectObject(sourceDc, bitmap);
            try
            {
                Marshal.Copy(pixels, 0, bits, pixels.Length);
                SetStretchBltMode(dc, 4); // HALFTONE: smooth, so letters stay readable
                StretchBlt(dc, 0, 0, newWidth, newHeight, sourceDc, 0, 0, width, height, SRCCOPY);
            }
            finally
            {
                SelectObject(sourceDc, old);
                DeleteObject(bitmap);
                DeleteDC(sourceDc);
                ReleaseDC(IntPtr.Zero, screen);
            }
        });
        return (scaled, newWidth, newHeight);
    }
}
