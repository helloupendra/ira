using IraKit;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using WinRT.Interop;

namespace Ira;

/// <summary>
/// Settings: the shortcut, the folders Ira may use, starting at sign-in and the skills allowed
/// on this PC; and "What I read", the calls Ira made here since it started (where, never what).
/// </summary>
internal sealed class SettingsWindow : Window
{
    /// <summary>The PC's skills, in the words Settings uses for them.</summary>
    private static readonly (string Skill, string Says)[] Skills =
    [
        ("files", "Files: find, read and open your files"),
        ("screen", "Screen: read the text of the window you are in"),
        ("browser", "Browser: list your tabs and bring one to the front"),
        ("apps", "Apps: open an app or a web link"),
        ("clipboard", "Clipboard: read what you copied"),
        ("control", "Control: type, press keys, click and scroll, each step after your PIN"),
        ("routine", "Routine: when this PC locks, sleeps and wakes, and which network it is on (as a code)"),
    ];

    private readonly IraController _controller;
    private readonly PanelWindow _panel;
    private readonly Action<IraKit.Shortcut> _shortcutChanged;
    private readonly DispatcherQueue _ui;
    private readonly StackPanel _settingsPage = new() { Spacing = 8 };
    private readonly StackPanel _readPage = new() { Spacing = 8, Visibility = Visibility.Collapsed };
    private readonly ComboBox _shortcut = new() { MinWidth = 220 };
    private readonly TextBlock _shortcutProblem = Note("");
    private readonly StackPanel _folders = new() { Spacing = 4 };
    private readonly StackPanel _skills = new() { Spacing = 4 };
    private readonly StackPanel _hello = new() { Spacing = 8 };
    private bool? _helloShown; // what the Hello section shows: null not paired, then off or on
    private readonly ListView _reads = new() { SelectionMode = ListViewSelectionMode.None };
    private readonly SelectorBarItem _readTab = new() { Text = "What I read" };
    private readonly SelectorBar _tabs = new();

    public SettingsWindow(IraController controller, PanelWindow panel, Action<IraKit.Shortcut> shortcutChanged)
    {
        _controller = controller;
        _panel = panel;
        _shortcutChanged = shortcutChanged;
        _ui = DispatcherQueue;
        Title = "Ira settings";
        SystemBackdrop = new MicaBackdrop();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(Scale(600), Scale(760)));

        var settingsTab = new SelectorBarItem { Text = "Settings" };
        _tabs.Items.Add(settingsTab);
        _tabs.Items.Add(_readTab);
        _tabs.SelectedItem = settingsTab;
        _tabs.SelectionChanged += (_, _) => ShowTab();

        BuildSettings();
        BuildReads();
        Content = new ScrollViewer
        {
            Content = new StackPanel
            {
                Padding = new Thickness(24, 16, 24, 24),
                Spacing = 12,
                Children = { _tabs, _settingsPage, _readPage },
            },
        };

        _controller.Changed += Render;
        _controller.Log.Changed += OnLogChanged;
        Closed += (_, _) =>
        {
            _controller.Changed -= Render;
            _controller.Log.Changed -= OnLogChanged;
        };
        Render();
        RenderReads();
    }

    /// <summary>Opens on "What I read".</summary>
    public void ShowReads() => _tabs.SelectedItem = _readTab;

    private void ShowTab()
    {
        var reading = _tabs.SelectedItem == _readTab;
        _settingsPage.Visibility = reading ? Visibility.Collapsed : Visibility.Visible;
        _readPage.Visibility = reading ? Visibility.Visible : Visibility.Collapsed;
    }

    // --- settings --------------------------------------------------------------------

    private void BuildSettings()
    {
        _shortcut.ItemsSource = IraKit.Shortcut.Choices.Select(c => c.Name).ToList();
        _shortcut.SelectedItem = _panel.Shortcut.Name;
        _shortcut.SelectionChanged += (_, _) => OnShortcutChosen();
        var addFolder = new Button { Content = "Add a folder…" };
        addFolder.Click += async (_, _) => await AddFolderAsync();
        var startAtLogin = new ToggleSwitch { Header = "Start Ira when you sign in to Windows", IsOn = StartAtLogin.IsOn };
        startAtLogin.Toggled += (_, _) => StartAtLogin.Set(startAtLogin.IsOn);

        Add(_settingsPage,
            Heading("Shortcut"),
            Note("Opens Ira from any app."),
            _shortcut,
            _shortcutProblem,
            Heading("Folders Ira may use"),
            Note(@"Your user folder, unless you add folders in it here: then only those. A folder elsewhere (D:\Work, say) is "
                + "added to what Ira may use. AppData, .ssh, hidden files and key files stay off wherever they are."),
            _folders,
            addFolder,
            Heading("Starting"),
            startAtLogin,
            Heading("Approving with Windows Hello"),
            Note("Confirm what needs your PIN with your face, finger or Windows Hello PIN instead. Setting it up asks "
                + "your Ira PIN once."),
            _hello,
            Heading("What Ira may use on this PC"),
            Note("A skill works here only when it is on for this PC in Your devices on your Ira (with your PIN) and "
                + "allowed here. Switch one off here and this PC refuses it, whatever your Ira asks."),
            _skills);
    }

    private void OnShortcutChosen()
    {
        if (_shortcut.SelectedItem is not string name || name == _panel.Shortcut.Name) return;
        var chosen = IraKit.Shortcut.Named(name);
        if (_panel.SetShortcut(chosen))
        {
            _shortcutProblem.Text = "";
            _controller.SavePreferences(_controller.Preferences with { Shortcut = chosen.Name });
            _shortcutChanged(chosen);
        }
        else
        {
            _shortcutProblem.Text = $"Another app uses {name}. Ira kept {_panel.Shortcut.Name}.";
            _shortcut.SelectedItem = _panel.Shortcut.Name;
        }
    }

    private async Task AddFolderAsync()
    {
        var picker = new Windows.Storage.Pickers.FolderPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(this));
        picker.FileTypeFilter.Add("*");
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null || string.IsNullOrEmpty(folder.Path)) return; // a library or a phone has no path
        var folders = _controller.Preferences.Folders;
        if (folders.Contains(folder.Path, StringComparer.OrdinalIgnoreCase)) return;
        _controller.SavePreferences(_controller.Preferences with { Folders = [.. folders, folder.Path] });
    }

    private void Render()
    {
        _folders.Children.Clear();
        var chosen = _controller.Preferences.Folders;
        if (chosen.Count == 0) _folders.Children.Add(Note("Your user folder"));
        foreach (var folder in chosen)
        {
            var remove = new Button { Content = "Remove" };
            remove.Click += (_, _) => _controller.SavePreferences(_controller.Preferences with
            {
                Folders = _controller.Preferences.Folders.Where(f => f != folder).ToList(),
            });
            _folders.Children.Add(Row(new TextBlock { Text = folder, VerticalAlignment = VerticalAlignment.Center }, remove));
        }

        RenderHello();
        _skills.Children.Clear();
        if (_controller.Settings is not { } paired)
        {
            _skills.Children.Add(Note("Pair this PC with your Ira first."));
            return;
        }
        foreach (var (skill, says) in Skills)
        {
            var onThere = _controller.ServerSkills.Contains(skill);
            var toggle = new ToggleSwitch
            {
                Header = onThere ? says : $"{says} (off for this PC in Your devices)",
                IsOn = paired.AllowedSkills.Contains(skill),
            };
            toggle.Toggled += (_, _) => _controller.SetAllowed(skill, toggle.IsOn);
            _skills.Children.Add(toggle);
        }
    }

    /// <summary>Built again only when it changes, so a PIN being typed is not wiped by a reconnect.</summary>
    private void RenderHello()
    {
        var state = _controller.Settings?.HelloApprovals;
        if (_hello.Children.Count > 0 && state == _helloShown) return;
        _helloShown = state;
        _hello.Children.Clear();
        if (state is null)
        {
            _hello.Children.Add(Note("Pair this PC with your Ira first."));
            return;
        }
        if (state == true)
        {
            var off = new Button { Content = "Turn off" };
            off.Click += async (_, _) =>
            {
                await HelloKey.DeleteAsync();
                _controller.SetHello(false);
            };
            _hello.Children.Add(Row(new TextBlock { Text = "On for this PC.", VerticalAlignment = VerticalAlignment.Center }, off));
            return;
        }
        var pin = new PasswordBox { PlaceholderText = "Your Ira PIN", Width = 160, MaxLength = 12 };
        var setUp = new Button { Content = "Set up Windows Hello" };
        var problem = Note("");
        setUp.Click += async (_, _) =>
        {
            setUp.IsEnabled = false;
            try
            {
                if (pin.Password.Length == 0) problem.Text = "Type your Ira PIN first.";
                else if (!await HelloKey.IsSupportedAsync())
                    problem.Text = "Windows Hello is not set up on this PC: set it up in Windows Settings, Accounts, Sign-in options.";
                else if (_controller.Ask is { } ask)
                {
                    var publicKey = await HelloKey.CreateAsync();
                    await ask.EnrolHelloAsync(publicKey, pin.Password);
                    _controller.SetHello(true);
                }
            }
            catch (DeviceRevokedError error)
            {
                _controller.Unpair(error.Message);
            }
            catch (IraError error)
            {
                problem.Text = error.Message;
            }
            finally
            {
                pin.Password = "";
                setUp.IsEnabled = true;
            }
        };
        _hello.Children.Add(Row(pin, setUp));
        _hello.Children.Add(problem);
    }

    // --- what I read -----------------------------------------------------------------

    private void BuildReads()
    {
        var clear = new Button { Content = "Clear" };
        clear.Click += (_, _) => _controller.Log.Clear();
        Add(_readPage,
            Note("What Ira used on this PC since it started, newest first: the file, search, window or app, never "
                + "what it read. It is kept only on this PC, and only until Ira quits."),
            clear,
            _reads);
    }

    private void OnLogChanged() => _ui.TryEnqueue(RenderReads);

    private void RenderReads()
    {
        var entries = _controller.Log.Entries;
        _reads.ItemsSource = entries.Count == 0
            ? new List<string> { "Nothing yet." }
            : entries.Select(e => $"{e.At.ToLocalTime():HH:mm}  {e.Line}").ToList();
    }

    // --- pieces ----------------------------------------------------------------------

    private static TextBlock Heading(string text) => new()
    {
        Text = text,
        Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"],
        Margin = new Thickness(0, 12, 0, 0),
    };

    private static TextBlock Note(string text) => new()
    {
        Text = text,
        TextWrapping = TextWrapping.Wrap,
        Foreground = (Brush)Application.Current.Resources["TextFillColorSecondaryBrush"],
    };

    private static StackPanel Row(params UIElement[] children)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        foreach (var child in children) row.Children.Add(child);
        return row;
    }

    private static void Add(Panel panel, params UIElement[] children)
    {
        foreach (var child in children) panel.Children.Add(child);
    }

    private int Scale(int dip) => (int)(dip * GetDpiForWindow(WindowNative.GetWindowHandle(this)) / 96.0);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);
}
