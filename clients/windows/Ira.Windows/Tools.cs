using IraKit;
using IraKit.Tools;

namespace Ira;

/// <summary>
/// The tools this PC offers Ira: files, screen, browser, apps and clipboard. Each runs only
/// when its skill is on in Ira (with the PIN) and allowed on this PC.
/// </summary>
internal static class Tools
{
    public static Toolbox Create(Func<PathPolicy> policy, ReadLog log)
    {
        var tools = PcTools.Create(ForegroundTracker.TargetWindow, policy);
        tools.Log = log;
        return tools;
    }
}
