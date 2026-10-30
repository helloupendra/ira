namespace IraKit.Tools;

/// <summary>
/// Every tool this PC offers Ira, as the hello lists them. The names, parameters and tiers are
/// the Mac's, so Ira treats both alike: files, screen, browser, apps and clipboard.
/// </summary>
public static class PcTools
{
    /// <param name="targetWindow">
    /// The window the person is in: the one in front, or, while Ira's own panel is in front,
    /// the one they were in just before.
    /// </param>
    /// <param name="policy">Where files may be found, read and opened (it can change in settings).</param>
    public static Toolbox Create(Func<IntPtr> targetWindow, Func<PathPolicy>? policy = null)
    {
        policy ??= PathPolicy.Current;
        var apps = new Cached<IReadOnlyList<AppTools.App>>(AppTools.StartMenuApps, TimeSpan.FromMinutes(5));
        return new Toolbox([
            .. new FileTools(policy).Tools(),
            new ScreenTools(targetWindow).Tool(),
            .. BrowserTools.Tools(),
            .. AppTools.Tools(apps.Get),
        ]);
    }

    /// <summary>A value worked out at most once in a while (the Start menu's apps take a moment to list).</summary>
    private sealed class Cached<T>(Func<T> make, TimeSpan keep)
    {
        private readonly Lock _lock = new();
        private (T Value, DateTime At)? _value;

        public T Get()
        {
            lock (_lock)
            {
                if (_value is { } cached && DateTime.UtcNow - cached.At < keep) return cached.Value;
                var value = make();
                _value = (value, DateTime.UtcNow);
                return value;
            }
        }
    }
}
