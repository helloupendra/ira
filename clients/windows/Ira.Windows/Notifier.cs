using System.Runtime.InteropServices;
using H.NotifyIcon;
using Microsoft.UI.Dispatching;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;

namespace Ira;

/// <summary>
/// Windows notifications with buttons (Copy, Open, Show in folder). If Windows will not take
/// Ira's notifications, a plain balloon from the tray icon says the same without buttons.
/// </summary>
public sealed class Notifier : IDisposable
{
    private readonly TaskbarIcon _tray;
    private readonly bool _registered;

    /// <summary>A button was pressed: its arguments ("action", "id"), on the UI thread.</summary>
    public event Action<IDictionary<string, string>>? Invoked;

    public Notifier(TaskbarIcon tray, DispatcherQueue ui)
    {
        _tray = tray;
        try
        {
            AppNotificationManager.Default.NotificationInvoked += (_, args) =>
            {
                var arguments = new Dictionary<string, string>(args.Arguments);
                ui.TryEnqueue(() => Invoked?.Invoke(arguments));
            };
            AppNotificationManager.Default.Register();
            _registered = true;
        }
        catch (Exception e) when (e is COMException or InvalidOperationException or UnauthorizedAccessException)
        {
            _registered = false;
        }
    }

    public void Show(string title, string body, params (string Label, string Action, string? Target)[] buttons)
    {
        if (!_registered)
        {
            _tray.ShowNotification(title, body);
            return;
        }
        var builder = new AppNotificationBuilder().AddText(title).AddText(body);
        foreach (var (label, action, target) in buttons)
        {
            builder.AddButton(new AppNotificationButton(label).AddArgument("action", action).AddArgument("id", target ?? ""));
        }
        try
        {
            AppNotificationManager.Default.Show(builder.BuildNotification());
        }
        catch (COMException)
        {
            _tray.ShowNotification(title, body); // notifications switched off for Ira: the balloon still shows
        }
    }

    public void Dispose()
    {
        if (_registered) AppNotificationManager.Default.Unregister();
    }
}
