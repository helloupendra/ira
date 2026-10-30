using IraKit;
using IraKit.Tools;

namespace Ira;

/// <summary>
/// The tools this PC offers Ira: files, screen, browser, apps and clipboard. Each runs only
/// when its skill is on in Ira (with the PIN) and allowed on this PC.
/// </summary>
internal static class Tools
{
    public static Toolbox Create() => PcTools.Create(ForegroundTracker.TargetWindow);
}
