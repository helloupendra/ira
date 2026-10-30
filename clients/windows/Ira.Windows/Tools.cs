using IraKit;

namespace Ira;

/// <summary>
/// The tools this PC offers Ira. Empty until the first wave of skills (files, screen, browser,
/// apps, clipboard) is built; the connection, asking and approvals work without them.
/// </summary>
internal static class Tools
{
    public static Toolbox Create() => new([]);
}
