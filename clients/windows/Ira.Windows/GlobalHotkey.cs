using System.Runtime.InteropServices;

namespace Ira;

/// <summary>
/// A system-wide shortcut (Ctrl+Alt+Space by default) that opens Ira from any app. Windows
/// sends it to the panel's window, which is listened to here.
/// </summary>
internal sealed class GlobalHotkey : IDisposable
{
    private const int WM_HOTKEY = 0x0312;
    private const uint MOD_ALT = 0x1, MOD_CONTROL = 0x2, MOD_NOREPEAT = 0x4000;
    private const uint VK_SPACE = 0x20;
    private const int Id = 0x1A1;

    private readonly IntPtr _window;
    private readonly SubclassProc _proc; // kept alive: Windows calls it for as long as it is set

    public event Action? Pressed;

    /// <summary>False when another app already owns this shortcut.</summary>
    public bool Registered { get; }

    public GlobalHotkey(IntPtr window)
    {
        _window = window;
        _proc = WindowProc;
        SetWindowSubclass(window, _proc, 1, 0);
        Registered = RegisterHotKey(window, Id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE);
    }

    private IntPtr WindowProc(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr data)
    {
        if (message == WM_HOTKEY && wParam == Id)
        {
            Pressed?.Invoke();
            return IntPtr.Zero;
        }
        return DefSubclassProc(hwnd, message, wParam, lParam);
    }

    public void Dispose()
    {
        UnregisterHotKey(_window, Id);
        RemoveWindowSubclass(_window, _proc, 1);
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
