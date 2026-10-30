using System.Diagnostics;
using IraKit;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;

namespace Ira;

/// <summary>
/// The person's Drop on this PC: the recent items, sending to the other devices, and the
/// connection's drop frames. Text from another device comes as a notification with Copy; a file
/// is saved to Downloads\Ira at once and announced with Show in folder. Runs on the UI thread.
/// </summary>
public sealed class DropBox
{
    private readonly IraController _controller;
    private readonly Notifier _notes;
    private readonly List<DropItem> _items = [];

    public DropBox(IraController controller, Notifier notes)
    {
        _controller = controller;
        _notes = notes;
        _controller.DropChanged += Handle;
        _controller.Connected += () => _ = CatchUpAsync();
        _notes.Invoked += args => _ = ActAsync(args);
    }

    /// <summary>The items, newest first.</summary>
    public IReadOnlyList<DropItem> Items => _items;

    /// <summary>The list changed: redraw.</summary>
    public event Action? Changed;

    /// <summary>Loads the latest items, quietly.</summary>
    public async Task RefreshAsync()
    {
        if (_controller.Drop is not { } client) return;
        await Guard(async () =>
        {
            var (items, _) = await client.ListAsync(limit: 50);
            _items.Clear();
            _items.AddRange(items);
            Changed?.Invoke();
        });
    }

    /// <summary>The connection is back: what arrived meanwhile, quietly (no notification for each).</summary>
    private async Task CatchUpAsync()
    {
        if (_items.Count == 0)
        {
            await RefreshAsync();
            return;
        }
        if (_controller.Drop is not { } client) return;
        await Guard(async () =>
        {
            var (items, _) = await client.ListAsync(afterId: _items.Max(i => i.Id));
            Merge(items);
        });
    }

    private void Handle(DropFrame frame)
    {
        switch (frame)
        {
            case DropFrame.New(var item):
                if (_items.Any(i => i.Id == item.Id)) return;
                Merge([item]);
                _ = ArrivedAsync(item);
                break;
            case DropFrame.Deleted(var id):
                if (_items.RemoveAll(i => i.Id == id) > 0) Changed?.Invoke();
                break;
        }
    }

    private void Merge(IEnumerable<DropItem> more)
    {
        foreach (var item in more.Where(m => _items.All(i => i.Id != m.Id))) _items.Add(item);
        _items.Sort((a, b) => b.Id.CompareTo(a.Id));
        if (_items.Count > 200) _items.RemoveRange(200, _items.Count - 200);
        Changed?.Invoke();
    }

    private async Task ArrivedAsync(DropItem item)
    {
        var from = item.FromLabel.Length > 0 ? item.FromLabel : "another device";
        if (!item.IsFile)
        {
            var buttons = new List<(string, string, string?)> { ("Copy", "copy", item.Id.ToString()) };
            if (item.Link is not null) buttons.Add(("Open", "open", item.Id.ToString()));
            _notes.Show($"From {from}", item.Preview, [.. buttons]);
            return;
        }
        try
        {
            var saved = await SaveAsync(item);
            _notes.Show($@"From {from}, in Downloads\Ira", item.Preview, ("Show in folder", "reveal", saved));
        }
        catch (IraError error)
        {
            _notes.Show($"In your Drop, from {from}", $"{item.Preview}. It did not save: {error.Message}");
        }
    }

    // --- sending ----------------------------------------------------------------------

    public async Task<bool> SendTextAsync(string text)
    {
        text = text.Trim();
        if (text.Length == 0 || _controller.Drop is not { } client) return false;
        return await Guard(async () =>
        {
            Merge([await client.SendTextAsync(text)]);
            _notes.Show("Sent to your devices", Preview(text));
        });
    }

    public async Task<bool> SendFilesAsync(IReadOnlyList<string> paths)
    {
        if (_controller.Drop is not { } client) return false;
        var files = paths.Where(File.Exists).ToList();
        if (files.Count == 0)
        {
            _notes.Show("Nothing to send", "Only files can be sent, not folders.");
            return false;
        }
        return await Guard(async () =>
        {
            foreach (var file in files) Merge([await client.SendFileAsync(file)]);
            _notes.Show("Sent to your devices", files.Count == 1 ? Path.GetFileName(files[0]) : $"{files.Count} files");
        });
    }

    /// <summary>The clipboard: files copied in File Explorer, else its text.</summary>
    public async Task SendClipboardAsync()
    {
        var content = Clipboard.GetContent();
        if (content.Contains(StandardDataFormats.StorageItems))
        {
            var items = await content.GetStorageItemsAsync();
            var files = items.OfType<StorageFile>().Select(f => f.Path).Where(p => p.Length > 0).ToList();
            if (files.Count > 0)
            {
                await SendFilesAsync(files);
                return;
            }
        }
        if (content.Contains(StandardDataFormats.Text) && await content.GetTextAsync() is { Length: > 0 } text)
        {
            await SendTextAsync(text);
            return;
        }
        _notes.Show("Nothing to send", "The clipboard is empty.");
    }

    // --- using an item ------------------------------------------------------------------

    /// <summary>Text or a link onto the clipboard; a file, saved first, as the file.</summary>
    public async Task CopyAsync(DropItem item)
    {
        var package = new DataPackage();
        if (item.IsFile)
        {
            string saved;
            try
            {
                saved = await SaveAsync(item);
            }
            catch (IraError error)
            {
                _notes.Show("Could not copy", error.Message);
                return;
            }
            package.SetStorageItems([await StorageFile.GetFileFromPathAsync(saved)]);
        }
        else
        {
            package.SetText(item.Text ?? "");
        }
        Clipboard.SetContent(package);
    }

    public async Task CopyLatestAsync()
    {
        if (_items.Count == 0) await RefreshAsync();
        if (_items.FirstOrDefault() is { } latest)
        {
            await CopyAsync(latest);
            _notes.Show("Copied from your Drop", latest.Preview);
        }
        else
        {
            _notes.Show("Your Drop is empty", "Nothing to copy yet.");
        }
    }

    /// <summary>A link in the browser; a file saved and shown in its folder.</summary>
    public async Task OpenAsync(DropItem item)
    {
        if (item.Link is { } link)
        {
            Process.Start(new ProcessStartInfo(link.AbsoluteUri) { UseShellExecute = true })?.Dispose();
        }
        else if (item.IsFile)
        {
            try
            {
                Reveal(await SaveAsync(item));
            }
            catch (IraError error)
            {
                _notes.Show("Could not save it", error.Message);
            }
        }
    }

    public async Task DeleteAsync(DropItem item)
    {
        if (_controller.Drop is not { } client) return;
        await Guard(async () =>
        {
            await client.DeleteAsync(item.Id);
            _items.RemoveAll(i => i.Id == item.Id);
            Changed?.Invoke();
        });
    }

    public static void OpenFolder()
    {
        Directory.CreateDirectory(Drop.Folder);
        Process.Start(new ProcessStartInfo("explorer.exe", $"\"{Drop.Folder}\"") { UseShellExecute = false })?.Dispose();
    }

    public static void Reveal(string path) =>
        Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"") { UseShellExecute = false })?.Dispose();

    /// <summary>A notification's button: Copy, Open or Show in folder.</summary>
    private async Task ActAsync(IDictionary<string, string> args)
    {
        var action = args.TryGetValue("action", out var a) ? a : "";
        var target = args.TryGetValue("id", out var t) ? t : "";
        if (action == "reveal")
        {
            if (File.Exists(target)) Reveal(target);
            return;
        }
        if (!long.TryParse(target, out var id)) return;
        var item = _items.FirstOrDefault(i => i.Id == id);
        if (item is null && _controller.Drop is { } client)
        {
            await Guard(async () => item = await client.GetAsync(id));
        }
        if (item is null) return;
        if (action == "copy") await CopyAsync(item);
        else if (action == "open") await OpenAsync(item);
    }

    private async Task<string> SaveAsync(DropItem item)
    {
        var client = _controller.Drop ?? throw new IraError("this PC is not paired");
        try
        {
            return await client.SaveAsync(item, Drop.Folder);
        }
        catch (DeviceRevokedError error)
        {
            _controller.Unpair(error.Message);
            throw;
        }
    }

    /// <summary>Runs a Drop call; a failure becomes a notification, a removed PC unpairs.</summary>
    private async Task<bool> Guard(Func<Task> call)
    {
        try
        {
            await call();
            return true;
        }
        catch (DeviceRevokedError error)
        {
            _controller.Unpair(error.Message);
        }
        catch (IraError error)
        {
            _notes.Show("Drop didn't work", error.Message);
        }
        return false;
    }

    private static string Preview(string text)
    {
        var line = string.Join(' ', text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return line.Length <= 120 ? line : line[..119] + "…";
    }
}
