using System.Runtime.InteropServices;

namespace Ira;

/// <summary>
/// The window the person is working in: whatever is in front, or, while Ira's own panel is in
/// front, the window they were in just before they opened it. "What's on my screen?" asked in
/// the panel means that window, not the panel.
/// </summary>
internal static class ForegroundTracker
{
    private const uint EVENT_SYSTEM_FOREGROUND = 0x0003, WINEVENT_OUTOFCONTEXT = 0;
    private static readonly uint OurProcess = (uint)Environment.ProcessId;
    private static WinEventProc? _proc; // kept alive while Windows calls it
    private static IntPtr _hook;
    private static IntPtr _last;

    /// <summary>Starts listening; call on the UI thread, which delivers the events.</summary>
    public static void Start()
    {
        Remember(GetForegroundWindow());
        _proc = (_, _, hwnd, _, _, _, _) => Remember(hwnd);
        _hook = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, IntPtr.Zero, _proc, 0, 0, WINEVENT_OUTOFCONTEXT);
    }

    public static void Stop()
    {
        if (_hook != IntPtr.Zero) UnhookWinEvent(_hook);
        _hook = IntPtr.Zero;
    }

    /// <summary>The window to read or act in.</summary>
    public static IntPtr TargetWindow()
    {
        var front = GetForegroundWindow();
        return IsOurs(front) ? _last : front;
    }

    private static void Remember(IntPtr hwnd)
    {
        if (hwnd != IntPtr.Zero && !IsOurs(hwnd)) _last = hwnd;
    }

    private static bool IsOurs(IntPtr hwnd)
    {
        GetWindowThreadProcessId(hwnd, out var pid);
        return pid == OurProcess;
    }

    private delegate void WinEventProc(IntPtr hook, uint eventType, IntPtr hwnd, int idObject, int idChild, uint thread, uint time);

    [DllImport("user32.dll")]
    private static extern IntPtr SetWinEventHook(uint min, uint max, IntPtr module, WinEventProc proc, uint pid, uint thread, uint flags);

    [DllImport("user32.dll")]
    private static extern bool UnhookWinEvent(IntPtr hook);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
}
