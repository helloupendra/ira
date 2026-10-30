using System.Runtime.InteropServices;
using IraKit;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;
using Windows.Graphics;
using Windows.System;
using WinRT.Interop;

namespace Ira;

/// <summary>
/// The one window: a panel above the tray that pairs the PC, then asks Ira and shows its
/// Yes/No and PIN cards, and holds the Drop. It hides when it loses focus (unless pinned, or
/// while the Drop is open, so files can be dragged in), and on Esc.
/// </summary>
public sealed partial class PanelWindow : Window
{
    private const int WidthDip = 420, HeightDip = 640, MarginDip = 12;

    private readonly IraController _controller;
    private readonly DropBox _drop;
    private readonly Action _quit;
    private readonly IntPtr _hwnd;
    private readonly GlobalHotkey _hotkey;
    private bool _pairAgain;   // the pairing page was asked for while already paired
    private bool _closing;
    private DateTime _hiddenAt;
    private string? _usedCode; // a code already paired with, still on the clipboard
    private string? _conversationId;
    private CancellationTokenSource? _asking;
    private IReadOnlyList<string> _skillsToAllow = [];

    public PanelWindow(IraController controller, DropBox drop, Action quit)
    {
        InitializeComponent();
        _controller = controller;
        _drop = drop;
        _quit = quit;
        _hwnd = WindowNative.GetWindowHandle(this);

        var presenter = OverlappedPresenter.Create();
        presenter.IsMaximizable = false;
        presenter.IsMinimizable = false;
        presenter.IsResizable = false;
        presenter.SetBorderAndTitleBar(hasBorder: true, hasTitleBar: false);
        AppWindow.SetPresenter(presenter);
        AppWindow.IsShownInSwitchers = false;
        AppWindow.Closing += (_, e) =>
        {
            if (_closing) return;
            e.Cancel = true; // Alt+F4 hides; Quit is in the menu
            HidePanel();
        };
        Activated += OnActivated;

        _hotkey = new GlobalHotkey(_hwnd);
        _hotkey.Pressed += TogglePanel;

        _controller.Changed += Render;
        _controller.SkillsToAllow += OnSkillsToAllow;
        _drop.Changed += RenderDrop;
        Render();
    }

    /// <summary>False when another app already has Ctrl+Alt+Space.</summary>
    public bool HotkeyRegistered => _hotkey.Registered;

    public void ShowPanel()
    {
        PlaceAboveTray();
        AppWindow.Show();
        Activate();
        SetForegroundWindow(_hwnd);
    }

    public void HidePanel()
    {
        _hiddenAt = DateTime.UtcNow;
        AppWindow.Hide();
    }

    public void TogglePanel()
    {
        if (AppWindow.IsVisible && GetForegroundWindow() == _hwnd) HidePanel();
        // A click on the tray icon first takes focus away, which already hid the panel: that
        // click meant "close", not "open again".
        else if (DateTime.UtcNow - _hiddenAt > TimeSpan.FromMilliseconds(400)) ShowPanel();
    }

    public void ShowPairAgain()
    {
        _pairAgain = true;
        Render();
        ShowPanel();
    }

    /// <summary>Closes the window for good, when Ira quits.</summary>
    public void Shutdown()
    {
        _closing = true;
        _asking?.Cancel();
        _hotkey.Dispose();
        Close();
    }

    // --- showing ---------------------------------------------------------------------

    private void Render()
    {
        var paired = _controller.IsPaired;
        var pairing = !paired || _pairAgain;
        var dropping = !pairing && DropTab.IsSelected;
        PairView.Visibility = pairing ? Visibility.Visible : Visibility.Collapsed;
        Tabs.Visibility = pairing ? Visibility.Collapsed : Visibility.Visible;
        ChatView.Visibility = !pairing && !dropping ? Visibility.Visible : Visibility.Collapsed;
        DropView.Visibility = dropping ? Visibility.Visible : Visibility.Collapsed;
        BackButton.Visibility = paired && _pairAgain ? Visibility.Visible : Visibility.Collapsed;
        ForgetItem.IsEnabled = paired;
        AssistantName.Text = _controller.Settings?.Assistant ?? "Ira";

        var host = _controller.Server?.Host;
        (StateDot.Fill, StateText.Text) = !paired ? (Brush("SystemFillColorNeutralBrush"), "Not paired")
            : _controller.State switch
            {
                ConnectionState.Connected => (Brush("SystemFillColorSuccessBrush"), $"{_controller.Settings!.Label} · connected to {host}"),
                ConnectionState.Connecting => (Brush("SystemFillColorCautionBrush"), $"Connecting to {host}…"),
                ConnectionState.Waiting => (Brush("SystemFillColorCriticalBrush"), $"Can't reach {host}. Trying again."),
                _ => (Brush("SystemFillColorNeutralBrush"), "Not connected"),
            };
        ToolTipService.SetToolTip(StateText, _controller.StateDetail);

        if (_controller.Notice is { } notice)
        {
            ShowPairNotice(notice, InfoBarSeverity.Warning);
        }
    }

    private void PlaceAboveTray()
    {
        GetCursorPos(out var cursor);
        var area = DisplayArea.GetFromPoint(new PointInt32(cursor.X, cursor.Y), DisplayAreaFallback.Primary).WorkArea;
        var scale = GetDpiForWindow(_hwnd) / 96.0;
        var margin = (int)(MarginDip * scale);
        var width = (int)(WidthDip * scale);
        var height = Math.Min((int)(HeightDip * scale), area.Height - 2 * margin);
        AppWindow.MoveAndResize(new RectInt32(
            area.X + area.Width - width - margin, area.Y + area.Height - height - margin, width, height));
    }

    private void OnActivated(object sender, WindowActivatedEventArgs args)
    {
        if (args.WindowActivationState == WindowActivationState.Deactivated)
        {
            // While pairing the person goes to copy the link; keep the page where it was.
            if (PinButton.IsChecked != true && ChatView.Visibility == Visibility.Visible) HidePanel();
            return;
        }
        // Activation puts focus back where it last was, which may be Allow or Yes: a stray key
        // would press it. Move it to a text box, after Windows has finished activating.
        DispatcherQueue.TryEnqueue(FocusTyping);
        if (PairView.Visibility == Visibility.Visible) _ = FillFromClipboardAsync(saySo: false);
    }

    /// <summary>Focus where typing is harmless: the question, or the address (Enter there does nothing).</summary>
    private void FocusTyping()
    {
        if (ChatView.Visibility == Visibility.Visible) AskBox.Focus(FocusState.Programmatic);
        else if (DropView.Visibility == Visibility.Visible) DropText.Focus(FocusState.Programmatic);
        else ServerBox.Focus(FocusState.Programmatic);
    }

    private void OnTabChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        Render();
        FocusTyping();
        if (DropTab.IsSelected && _drop.Items.Count == 0) _ = _drop.RefreshAsync();
    }

    private void OnRootKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Escape) return;
        e.Handled = true;
        HidePanel();
    }

    private void OnPinClick(object sender, RoutedEventArgs e) =>
        ToolTipService.SetToolTip(PinButton, PinButton.IsChecked == true ? "Hide Ira when I click away" : "Keep Ira open");

    // --- pairing ---------------------------------------------------------------------

    private async Task FillFromClipboardAsync(bool saySo)
    {
        string text;
        try
        {
            var content = Clipboard.GetContent();
            text = content.Contains(StandardDataFormats.Text) ? await content.GetTextAsync() : "";
        }
        catch (Exception e) when (e is COMException or UnauthorizedAccessException)
        {
            return; // another app holds the clipboard right now
        }

        var link = PairingLink.Find(text);
        if (link is null || link.Code == _usedCode)
        {
            if (saySo) ShowPairNotice("There's no pairing link on the clipboard. Copy it in Ira and try again.", InfoBarSeverity.Informational);
            return;
        }
        if (link.Server is not null) ServerBox.Text = link.Server.ToString();
        CodeBox.Text = link.Code;
        // Never paired by itself: a link someone else sent would join this PC to their Ira.
        var found = link.Server is null
            ? "Found the code you copied. Type your Ira's address, then press Pair."
            : $"Found the link you copied, for {link.Server.Host}. Pair only with your own Ira.";
        if (_controller.Notice is { } notice) ShowPairNotice($"{notice} {found}", InfoBarSeverity.Warning);
        else ShowPairNotice(found, InfoBarSeverity.Success);
    }

    private async void OnPasteClick(object sender, RoutedEventArgs e) => await FillFromClipboardAsync(saySo: true);

    private void OnCodeKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Enter) return;
        e.Handled = true;
        OnPairClick(sender, e);
    }

    private async void OnPairClick(object sender, RoutedEventArgs e)
    {
        PairNotice.IsOpen = false;
        if (!ServerAddress.TryParse(ServerBox.Text.Trim(), out var server, out var problem))
        {
            ShowPairNotice(problem, InfoBarSeverity.Error);
            return;
        }
        if (PairingLink.NormalizeCode(CodeBox.Text) is not { } code)
        {
            ShowPairNotice("A pairing code has 8 letters and digits, like ABCD-EFGH.", InfoBarSeverity.Error);
            return;
        }
        if (_controller.Server is { } current && current.ToString() != server!.ToString()
            && !await ConfirmSwitchAsync(current, server))
        {
            return;
        }

        SetPairing(busy: true);
        try
        {
            var result = await _controller.PairAsync(server!, code);
            _usedCode = code;
            _pairAgain = false;
            CodeBox.Text = "";
            PairNotice.IsOpen = false;
            NewConversation();
            Render();
            AddNote($"Paired as {result.Label}. Ask {result.Name} anything.");
            AskBox.Focus(FocusState.Programmatic);
        }
        catch (IraError error)
        {
            ShowPairNotice(error.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetPairing(busy: false);
        }
    }

    private async Task<bool> ConfirmSwitchAsync(ServerAddress current, ServerAddress next)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = Root.XamlRoot,
            Title = "Pair with a different Ira?",
            Content = $"This PC is paired with {current.Host}. Pairing it with {next.Host} replaces that: "
                + $"{current.Host} will no longer reach this PC.",
            PrimaryButtonText = $"Pair with {next.Host}",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private void SetPairing(bool busy)
    {
        PairRing.IsActive = busy;
        PairButton.IsEnabled = PasteButton.IsEnabled = ServerBox.IsEnabled = CodeBox.IsEnabled = !busy;
    }

    private void ShowPairNotice(string text, InfoBarSeverity severity)
    {
        PairNotice.Message = text;
        PairNotice.Severity = severity;
        PairNotice.IsOpen = true;
    }

    private void OnBackClick(object sender, RoutedEventArgs e)
    {
        _pairAgain = false;
        PairNotice.IsOpen = false;
        Render();
    }

    private void OnPairAgain(object sender, RoutedEventArgs e) => ShowPairAgain();

    private async void OnForget(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = Root.XamlRoot,
            Title = "Forget this pairing?",
            Content = "Ira for Windows deletes its device key and stops connecting. "
                + "To remove the PC from Ira as well, delete it on Ira's Devices page.",
            PrimaryButtonText = "Forget",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        _asking?.Cancel();
        NewConversation();
        _controller.Unpair();
    }

    private void OnQuit(object sender, RoutedEventArgs e) => _quit();

    // --- skills ----------------------------------------------------------------------

    private void OnSkillsToAllow(IReadOnlyList<string> skills)
    {
        _skillsToAllow = skills;
        SkillsText.Text = $"Ira turned on {string.Join(", ", skills)} for this PC. Allow them here? "
            + "Until you do, Ira can't use them on this PC.";
        SkillsBar.Visibility = Visibility.Visible;
    }

    private void OnAllowSkills(object sender, RoutedEventArgs e)
    {
        _controller.Allow(_skillsToAllow);
        OnNotNowSkills(sender, e);
    }

    private void OnNotNowSkills(object sender, RoutedEventArgs e)
    {
        SkillsBar.Visibility = Visibility.Collapsed;
        FocusTyping();
    }

    // --- drop ------------------------------------------------------------------------

    private void RenderDrop()
    {
        DropList.Children.Clear();
        if (_drop.Items.Count == 0)
        {
            DropList.Children.Add(Caption("Nothing yet. Text, links and files you send from any of your devices show here for 30 days."));
            return;
        }
        foreach (var item in _drop.Items) DropList.Children.Add(DropRow(item));
    }

    private Border DropRow(DropItem item)
    {
        var glyph = item.IsFile ? "" : item.Link is not null ? "" : "";
        var grid = new Grid { ColumnSpacing = 10 };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.Children.Add(new FontIcon { Glyph = glyph, FontSize = 16, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 2, 0, 0) });

        var words = new StackPanel { Spacing = 2 };
        words.Children.Add(new TextBlock { Text = item.Preview, TextWrapping = TextWrapping.Wrap, MaxLines = 3, TextTrimming = TextTrimming.CharacterEllipsis });
        words.Children.Add(Caption($"From {(item.FromLabel.Length > 0 ? item.FromLabel : "a device")} · {When(item.CreatedAt)}"));
        Grid.SetColumn(words, 1);
        grid.Children.Add(words);

        var buttons = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Top };
        buttons.Children.Add(IconButton("", item.IsFile ? "Copy the file" : "Copy", () => _ = _drop.CopyAsync(item)));
        if (item.IsFile || item.Link is not null)
        {
            buttons.Children.Add(IconButton(item.IsFile ? "" : "",
                item.IsFile ? "Save and show in folder" : "Open in the browser", () => _ = _drop.OpenAsync(item)));
        }
        buttons.Children.Add(IconButton("", "Delete from every device", () => _ = _drop.DeleteAsync(item)));
        Grid.SetColumn(buttons, 2);
        grid.Children.Add(buttons);

        return new Border
        {
            Child = grid,
            Padding = new Thickness(10),
            CornerRadius = new CornerRadius(8),
            Background = Brush("CardBackgroundFillColorDefaultBrush"),
        };
    }

    private static Button IconButton(string glyph, string tip, Action click)
    {
        var button = new Button
        {
            Content = new FontIcon { Glyph = glyph, FontSize = 14 },
            Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent),
            BorderThickness = new Thickness(0),
            Padding = new Thickness(6),
        };
        ToolTipService.SetToolTip(button, tip);
        AutomationProperties.SetName(button, tip);
        button.Click += (_, _) => click();
        return button;
    }

    /// <summary>"just now", "5 min ago", "3 h ago", "yesterday", or the date.</summary>
    private static string When(string? created)
    {
        if (!DateTimeOffset.TryParse(created, System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AssumeUniversal, out var at))
        {
            return "";
        }
        var ago = DateTimeOffset.Now - at;
        if (ago < TimeSpan.FromMinutes(1)) return "just now";
        if (ago < TimeSpan.FromHours(1)) return $"{(int)ago.TotalMinutes} min ago";
        if (ago < TimeSpan.FromHours(24)) return $"{(int)ago.TotalHours} h ago";
        return ago < TimeSpan.FromHours(48) ? "yesterday" : at.ToLocalTime().ToString("d MMM");
    }

    private void OnDropTextKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Enter) return;
        e.Handled = true;
        OnDropSendClick(sender, e);
    }

    private async void OnDropSendClick(object sender, RoutedEventArgs e)
    {
        var text = DropText.Text;
        DropText.Text = "";
        if (!await _drop.SendTextAsync(text)) DropText.Text = text;
    }

    private async void OnDropFilesClick(object sender, RoutedEventArgs e)
    {
        var picker = new Windows.Storage.Pickers.FileOpenPicker();
        InitializeWithWindow.Initialize(picker, _hwnd);
        picker.FileTypeFilter.Add("*");
        var files = await picker.PickMultipleFilesAsync();
        if (files.Count > 0) await _drop.SendFilesAsync(files.Select(f => f.Path).ToList());
    }

    private void OnDragOver(object sender, DragEventArgs e)
    {
        if (!_controller.IsPaired) return;
        if (e.DataView.Contains(StandardDataFormats.StorageItems) || e.DataView.Contains(StandardDataFormats.Text))
        {
            e.AcceptedOperation = DataPackageOperation.Copy;
            e.DragUIOverride.Caption = "Send to your devices";
        }
    }

    private async void OnDrop(object sender, DragEventArgs e)
    {
        if (!_controller.IsPaired) return;
        var deferral = e.GetDeferral();
        try
        {
            DropTab.IsSelected = true;
            if (e.DataView.Contains(StandardDataFormats.StorageItems))
            {
                var items = await e.DataView.GetStorageItemsAsync();
                await _drop.SendFilesAsync(items.OfType<Windows.Storage.StorageFile>().Select(f => f.Path).ToList());
            }
            else if (e.DataView.Contains(StandardDataFormats.Text))
            {
                await _drop.SendTextAsync(await e.DataView.GetTextAsync());
            }
        }
        finally
        {
            deferral.Complete();
        }
    }


    // --- asking ----------------------------------------------------------------------

    private void OnAskKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Enter) return;
        e.Handled = true;
        _ = SendAsync();
    }

    private void OnSendClick(object sender, RoutedEventArgs e) => _ = SendAsync();

    private void OnNewConversation(object sender, RoutedEventArgs e) => NewConversation();

    private void NewConversation()
    {
        _asking?.Cancel();
        _conversationId = null;
        Messages.Children.Clear();
        Messages.Children.Add(EmptyHint);
        EmptyHint.Visibility = Visibility.Visible;
    }

    private async Task SendAsync()
    {
        var text = AskBox.Text.Trim();
        if (text.Length == 0 || _asking is not null || _controller.Ask is not { } ask) return;

        AskBox.Text = "";
        EmptyHint.Visibility = Visibility.Collapsed;
        AddBubble(text, mine: true);
        var working = AddNote("Thinking…");
        TextBlock? reply = null;
        var asking = _asking = new CancellationTokenSource();
        SendButton.IsEnabled = false;
        ScrollToEnd();
        try
        {
            await foreach (var e in ask.AskAsync(text, _conversationId, asking.Token))
            {
                switch (e)
                {
                    case AskEvent.Started started:
                        _conversationId = started.ConversationId;
                        break;
                    case AskEvent.ToolCalled tool:
                        working.Text = $"Using {Words(tool.Name)}…";
                        break;
                    case AskEvent.ToolFinished { Ok: false } tool:
                        AddNote($"{Words(tool.Name)} didn't work.");
                        break;
                    case AskEvent.Proposed proposed:
                        AddApproval(ask, proposed.Action);
                        break;
                    case AskEvent.Delta delta:
                        (reply ??= AddBubble("", mine: false)).Text += delta.Text;
                        break;
                    case AskEvent.Failed failed:
                        AddProblem(failed.Message);
                        break;
                    case AskEvent.Done done when !string.IsNullOrWhiteSpace(done.Text):
                        (reply ??= AddBubble("", mine: false)).Text = done.Text;
                        break;
                }
                ScrollToEnd();
            }
        }
        catch (DeviceRevokedError error)
        {
            _controller.Unpair(error.Message);
        }
        catch (IraError error)
        {
            AddProblem(error.Message);
        }
        catch (OperationCanceledException) when (asking.IsCancellationRequested)
        {
        }
        finally
        {
            Messages.Children.Remove(working);
            asking.Dispose();
            _asking = null;
            SendButton.IsEnabled = true;
            ScrollToEnd();
        }
    }

    /// <summary>A card for an action Ira wants to take: Yes/No for Tier 2, the PIN for Tier 3.</summary>
    private void AddApproval(AskClient ask, ProposedAction action)
    {
        var yesNo = action.Tier == 2 && action.CanApprove;
        var withPin = !yesNo && action.CanConfirm;

        var card = new StackPanel { Spacing = 8 };
        card.Children.Add(new TextBlock
        {
            Text = action.Summary,
            TextWrapping = TextWrapping.Wrap,
            Style = Style("BodyStrongTextBlockStyle"),
        });
        var status = Caption(yesNo ? "Ira asks before doing this."
            : withPin ? "This needs your PIN."
            : "Someone allowed to confirm this does it in Ira.");
        card.Children.Add(status);

        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        var pin = new PasswordBox { PlaceholderText = "PIN", Width = 110, MaxLength = 12 };
        var yes = new Button { Content = withPin ? "Confirm" : "Yes", Style = Style("AccentButtonStyle") };
        var no = new Button { Content = yesNo ? "No" : "Cancel" };
        if (withPin) buttons.Children.Add(pin);
        if (yesNo || withPin) buttons.Children.Add(yes);
        buttons.Children.Add(no);
        card.Children.Add(buttons);

        async Task Decide(Func<Task<ActionOutcome>> call)
        {
            buttons.IsHitTestVisible = false;
            buttons.Opacity = 0.5;
            ActionOutcome outcome;
            try
            {
                outcome = await call();
            }
            catch (DeviceRevokedError error)
            {
                _controller.Unpair(error.Message);
                return;
            }
            catch (IraError error)
            {
                status.Text = error.Message;
                buttons.IsHitTestVisible = true;
                buttons.Opacity = 1;
                return;
            }

            var tryAgain = outcome.Status == "wrong_pin";
            status.Text = outcome.Status switch
            {
                "executed" => "Done.",
                "cancelled" => "Cancelled.",
                "wrong_pin" => outcome.AttemptsLeft is { } left ? $"Wrong PIN. {left} more tries." : "Wrong PIN.",
                "locked" => $"Too many wrong PINs. Try again in {Math.Max(1, (outcome.LockedSeconds ?? 60) / 60)} min.",
                "expired" => "This waited too long. Ask again.",
                "already_done" => "This was already answered.",
                _ => outcome.Message ?? outcome.Status,
            };
            if (tryAgain)
            {
                pin.Password = "";
                buttons.IsHitTestVisible = true;
                buttons.Opacity = 1;
                pin.Focus(FocusState.Programmatic);
            }
            else
            {
                buttons.Visibility = Visibility.Collapsed;
                FocusTyping();
            }
            if (!string.IsNullOrWhiteSpace(outcome.Reply)) AddBubble(outcome.Reply, mine: false);
            ScrollToEnd();
        }

        yes.Click += async (_, _) => await Decide(() =>
            withPin ? ask.ConfirmAsync(action.Id, pin.Password) : ask.ApproveAsync(action.Id));
        no.Click += async (_, _) => await Decide(() => ask.CancelAsync(action.Id));
        pin.KeyDown += (_, e) =>
        {
            if (e.Key != VirtualKey.Enter || pin.Password.Length == 0) return;
            e.Handled = true;
            _ = Decide(() => ask.ConfirmAsync(action.Id, pin.Password));
        };

        Messages.Children.Add(new Border
        {
            Child = card,
            Padding = new Thickness(12),
            CornerRadius = new CornerRadius(8),
            BorderThickness = new Thickness(1),
            BorderBrush = Brush("AccentFillColorDefaultBrush"),
            Background = Brush("CardBackgroundFillColorDefaultBrush"),
        });
        if (withPin) pin.Focus(FocusState.Programmatic);
    }

    private TextBlock AddBubble(string text, bool mine)
    {
        var block = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
        if (mine) block.Foreground = Brush("TextOnAccentFillColorPrimaryBrush");
        Messages.Children.Add(new Border
        {
            Child = block,
            Padding = new Thickness(12, 8, 12, 8),
            CornerRadius = new CornerRadius(8),
            MaxWidth = 340,
            HorizontalAlignment = mine ? HorizontalAlignment.Right : HorizontalAlignment.Left,
            Background = Brush(mine ? "AccentFillColorDefaultBrush" : "CardBackgroundFillColorDefaultBrush"),
        });
        return block;
    }

    private TextBlock AddNote(string text)
    {
        var note = Caption(text);
        note.Margin = new Thickness(4, 0, 4, 0);
        Messages.Children.Add(note);
        return note;
    }

    private void AddProblem(string text)
    {
        var problem = AddNote(text);
        problem.Foreground = Brush("SystemFillColorCriticalBrush");
    }

    private void ScrollToEnd() => DispatcherQueue.TryEnqueue(() =>
    {
        Scroller.UpdateLayout();
        Scroller.ChangeView(null, Scroller.ScrollableHeight, null, disableAnimation: true);
    });

    /// <summary>"files_find" becomes "files find".</summary>
    private static string Words(string tool) => tool.Replace('_', ' ');

    private static TextBlock Caption(string text) => new()
    {
        Text = text,
        TextWrapping = TextWrapping.Wrap,
        Style = Style("CaptionTextBlockStyle"),
        Foreground = Brush("TextFillColorSecondaryBrush"),
    };

    private static Brush Brush(string key) => (Brush)Application.Current.Resources[key];

    private static Style Style(string key) => (Style)Application.Current.Resources[key];

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X, Y;
    }

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT point);

    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hwnd);
}
