using H.NotifyIcon;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace Ira;

/// <summary>
/// Ira for Windows lives in the tray: no window at start (except the first time, to pair),
/// the panel on its shortcut (Ctrl+Alt+Space unless changed in Settings) or a click on the tray icon.
/// </summary>
public partial class App : Application
{
    private PanelWindow? _panel;
    private TaskbarIcon? _tray;
    private Notifier? _notes;
    private DropBox? _drop;
    private SettingsWindow? _settings;
    private readonly Inbox _inbox = new();
    private Mutex? _onlyOne;

    public static IraController Controller { get; } = new();

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        var dropped = Inbox.DroppedFiles(Environment.GetCommandLineArgs());
        // One Ira per signed-in person: a second copy would fight the first for the hotkey and
        // the device connection (the server keeps only the newest). It hands over what it was
        // started for (files from Send to, or "show the panel") and leaves.
        _onlyOne = new Mutex(initiallyOwned: true, @"Local\IraForWindows", out var first);
        if (!first)
        {
            Inbox.Send(new Inbox.Message(dropped.Length == 0, dropped));
            Exit();
            return;
        }

        var ui = DispatcherQueue.GetForCurrentThread();
        ForegroundTracker.Start();
        _tray = CreateTray();
        _notes = new Notifier(_tray, ui);
        _drop = new DropBox(Controller, _notes);
        _panel = new PanelWindow(Controller, _drop, Quit);
        _panel.SettingsRequested += () => OpenSettings();
        _tray.ToolTipText = $"Ira ({_panel.Shortcut.Name})";
        StartAtLogin.Refresh();
        Controller.EventReceived += e => _notes.Show(e.Title, e.Text);
        _inbox.Received += message =>
        {
            if (message.Files.Length > 0) _ = _drop.SendFilesAsync(message.Files);
            else _panel.ShowPanel();
        };
        _inbox.Start(ui);
        SendTo.Install();

        Controller.Start(ui);
        if (!_panel.HotkeyRegistered)
        {
            _notes.Show($"{_panel.Shortcut.Name} is taken", "Another app uses that shortcut. Open Ira from its icon in the tray, "
                + "or choose another shortcut in Settings.");
        }
        if (!_panel.DropHotkeysRegistered)
        {
            _notes.Show("A Drop shortcut is taken", "Another app uses Ctrl+Alt+Shift+V or C. Both are in the tray icon's menu too.");
        }
        if (!Controller.IsPaired) _panel.ShowPanel(); // the first run opens on the pairing page
        else if (dropped.Length > 0) _ = _drop.SendFilesAsync(dropped);
    }

    private TaskbarIcon CreateTray()
    {
        var menu = new MenuFlyout();
        menu.Items.Add(Item("Open Ira", () => _panel!.ShowPanel()));
        menu.Items.Add(new MenuFlyoutSeparator());
        menu.Items.Add(Item("Send clipboard to your devices (Ctrl+Alt+Shift+V)", () => Paired(() => _ = _drop!.SendClipboardAsync())));
        menu.Items.Add(Item("Copy latest from Drop (Ctrl+Alt+Shift+C)", () => Paired(() => _ = _drop!.CopyLatestAsync())));
        menu.Items.Add(Item(@"Open Downloads\Ira", DropBox.OpenFolder));
        menu.Items.Add(new MenuFlyoutSeparator());
        menu.Items.Add(Item("What I read…", () => OpenSettings(reads: true)));
        menu.Items.Add(Item("Settings…", () => OpenSettings()));
        menu.Items.Add(Item("Pair again…", () => _panel!.ShowPairAgain()));
        menu.Items.Add(Item("Quit Ira", Quit));

        var tray = new TaskbarIcon
        {
            ToolTipText = "Ira",
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

    /// <summary>One Settings window at a time: opening it again brings it to the front.</summary>
    private void OpenSettings(bool reads = false)
    {
        if (_settings is null)
        {
            _settings = new SettingsWindow(Controller, _panel!, shortcut => _tray!.ToolTipText = $"Ira ({shortcut.Name})");
            _settings.Closed += (_, _) => _settings = null;
        }
        if (reads) _settings.ShowReads();
        _settings.Activate();
    }

    /// <summary>Runs a Drop action, or opens the pairing page when there is nothing to send with.</summary>
    private void Paired(Action action)
    {
        if (Controller.IsPaired) action();
        else _panel!.ShowPanel();
    }

    private static MenuFlyoutItem Item(string text, Action run) => new() { Text = text, Command = new Command(run) };

    private void Quit()
    {
        Controller.Stop();
        ForegroundTracker.Stop();
        _inbox.Dispose();
        _notes?.Dispose();
        _tray?.Dispose();
        _settings?.Close();
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
