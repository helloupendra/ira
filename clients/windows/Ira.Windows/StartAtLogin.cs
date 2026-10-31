using Microsoft.Win32;

namespace Ira;

/// <summary>
/// Ira starting when the person signs in to Windows: a value under their own Run key (no
/// administrator needed), which Settings switches on and off.
/// </summary>
internal static class StartAtLogin
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string Name = "Ira";

    public static bool IsOn
    {
        get
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKey);
            return key?.GetValue(Name) is string;
        }
    }

    public static void Set(bool on)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (on) key.SetValue(Name, $"\"{Environment.ProcessPath}\"");
        else key.DeleteValue(Name, throwOnMissingValue: false);
    }

    /// <summary>Points the value at this copy of Ira, when it is on and the app has moved.</summary>
    public static void Refresh()
    {
        if (IsOn) Set(true);
    }
}
