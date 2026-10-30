using H.NotifyIcon;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace Ira;

/// <summary>
/// Ira for Windows lives in the tray: no window at start (except the first time, to pair),
/// the panel on Ctrl+Alt+Space or a click on the tray icon.
/// </summary>
public partial class App : Application
{
    private PanelWindow? _panel;
    private TaskbarIcon? _tray;
    private Mutex? _onlyOne;

    public static IraController Controller { get; } = new();

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // One Ira per signed-in person: a second copy would fight the first for the hotkey and
        // the device connection (the server keeps only the newest).
        _onlyOne = new Mutex(initiallyOwned: true, @"Local\IraForWindows", out var first);
        if (!first)
        {
            Exit();
            return;
        }

        _panel = new PanelWindow(Controller, Quit);
        _tray = CreateTray();
        Controller.EventReceived += e => _tray.ShowNotification(e.Title, e.Text);
        Controller.Start(DispatcherQueue.GetForCurrentThread());
        if (!_panel.HotkeyRegistered)
        {
            _tray.ShowNotification("Ctrl+Alt+Space is taken",
                "Another app uses that shortcut. Open Ira from its icon in the tray.");
        }
        if (!Controller.IsPaired) _panel.ShowPanel(); // the first run opens on the pairing page
    }

    private TaskbarIcon CreateTray()
    {
        var menu = new MenuFlyout();
        menu.Items.Add(Item("Open Ira", () => _panel!.ShowPanel()));
        menu.Items.Add(new MenuFlyoutSeparator());
        menu.Items.Add(Item("Pair again…", () => _panel!.ShowPairAgain()));
        menu.Items.Add(Item("Quit Ira", Quit));

        var tray = new TaskbarIcon
        {
            ToolTipText = "Ira (Ctrl+Alt+Space)",
            IconSource = new GeneratedIconSource
            {
                Text = "I",
                Foreground = new SolidColorBrush(Colors.White),
                Background = new SolidColorBrush(ColorHelper.FromArgb(255, 27, 122, 75)),
                FontSize = 36,
            },
            ContextFlyout = menu,
            // The native menu: SecondWindow mode keeps a hidden window that takes focus at start.
            ContextMenuMode = ContextMenuMode.PopupMenu,
            NoLeftClickDelay = true,
            LeftClickCommand = new Command(() => _panel!.TogglePanel()),
        };
        tray.ForceCreate();
        return tray;
    }

    private static MenuFlyoutItem Item(string text, Action run) => new() { Text = text, Command = new Command(run) };

    private void Quit()
    {
        Controller.Stop();
        _tray?.Dispose();
        _panel?.Shutdown();
        _onlyOne?.ReleaseMutex();
        Exit();
    }
}

/// <summary>A command that just runs an action.</summary>
internal sealed class Command(Action run) : System.Windows.Input.ICommand
{
    public event EventHandler? CanExecuteChanged { add { } remove { } }
    public bool CanExecute(object? parameter) => true;
    public void Execute(object? parameter) => run();
}
