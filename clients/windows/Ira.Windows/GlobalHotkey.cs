using System.Runtime.InteropServices;

namespace Ira;

/// <summary>
/// A system-wide shortcut, from any app: Ctrl+Alt+Space opens Ira, and Drop's two
/// (Ctrl+Alt+Shift+V sends the clipboard, Ctrl+Alt+Shift+C copies the newest item). Windows
/// sends each to the panel's window, which is listened to here.
/// </summary>
internal sealed class GlobalHotkey : IDisposable
{
    private const int WM_HOTKEY = 0x0312;
    private const uint MOD_ALT = 0x1, MOD_CONTROL = 0x2, MOD_NOREPEAT = 0x4000;
    public const uint MOD_SHIFT = 0x4;
    private const uint VK_SPACE = 0x20;
    public const uint VK_C = 0x43, VK_V = 0x56;

    private readonly IntPtr _window;
    private readonly int _id;
    private readonly SubclassProc _proc; // kept alive: Windows calls it for as long as it is set

    public event Action? Pressed;

    /// <summary>False when another app already owns this shortcut.</summary>
    public bool Registered { get; }

    /// <summary>Ctrl+Alt+Space, which opens Ira.</summary>
    public GlobalHotkey(IntPtr window) : this(window, 0x1A1, 0, VK_SPACE) { }

    /// <summary>Ctrl+Alt with [moreModifiers] and [key], under its own [id].</summary>
    public GlobalHotkey(IntPtr window, int id, uint moreModifiers, uint key)
    {
        _window = window;
        _id = id;
        _proc = WindowProc;
        SetWindowSubclass(window, _proc, (nuint)id, 0);
        Registered = RegisterHotKey(window, id, MOD_CONTROL | MOD_ALT | moreModifiers | MOD_NOREPEAT, key);
    }

    private IntPtr WindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr data)
    {
        if (message == WM_HOTKEY && wParam == _id)
        {
            Pressed?.Invoke();
            return IntPtr.Zero;
        }
        return DefSubclassProc(hwnd, message, wParam, lParam);
    }

    public void Dispose()
    {
        UnregisterHotKey(_window, _id);
        RemoveWindowSubclass(_window, _proc, (nuint)_id);
    }

    private delegate IntPtr SubclassProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr data);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hwnd, int id, uint modifiers, uint key);

    [DllImport("user32.dll")]
    private static extern bool UnregisterHotKey(IntPtr hwnd, int id);

    [DllImport("comctl32.dll")]
    private static extern bool SetWindowSubclass(IntPtr hwnd, SubclassProc proc, nuint id, nuint data);

    [DllImport("comctl32.dll")]
    private static extern bool RemoveWindowSubclass(IntPtr hwnd, SubclassProc proc, nuint id);

    [DllImport("comctl32.dll")]
    private static extern IntPtr DefSubclassProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
}
