using System.Text.Json.Nodes;
using IraKit;
using IraKit.Tools;

namespace IraKit.Windows.Tests;

public class ReadLogAndPreferencesTests
{
    private const string Home = @"C:\Users\you";

    [Fact]
    public void What_I_read_names_the_place_never_the_contents()
    {
        Assert.Equal(@"~\Downloads\plan.pdf", ReadLog.Target("file_read", new JsonObject { ["path"] = @"C:\Users\you\Downloads\plan.pdf" }, home: Home));
        Assert.Equal(@"D:\Work\notes.md", ReadLog.Target("file_open", new JsonObject { ["path"] = @"D:\Work\notes.md" }, home: Home));
        Assert.Equal("“invoice”, pdf, last 7 days, in Downloads", ReadLog.Target("files_find", new JsonObject
        {
            ["query"] = "invoice", ["kind"] = "pdf", ["modifiedWithinDays"] = 7, ["folder"] = "Downloads",
        }));
        Assert.Equal("recent files", ReadLog.Target("files_find", []));
        Assert.Equal("chrome.exe", ReadLog.Target("screen_read", [], new JsonObject { ["app"] = "chrome.exe", ["text"] = "the page" }));
        Assert.Equal("all browsers", ReadLog.Target("browser_tabs", []));
        Assert.Equal("example.com", ReadLog.Target("url_open", new JsonObject { ["url"] = "https://example.com/a?b=c" }));
        Assert.Equal("", ReadLog.Target("clipboard_read", []));

        var entry = new ReadEntry(DateTimeOffset.Now, "file_read", @"~\a.txt", Ok: false);
        Assert.Equal(@"Read a file: ~\a.txt (did not run)", entry.Line);
    }

    [Fact]
    public void The_log_keeps_the_newest_first_and_only_so_many()
    {
        var log = new ReadLog();
        var changes = 0;
        log.Changed += () => changes++;
        for (var i = 0; i < ReadLog.Keep + 5; i++) log.Add(new ReadEntry(DateTimeOffset.Now, "app_open", $"app {i}", true));
        Assert.Equal(ReadLog.Keep, log.Entries.Count);
        Assert.Equal($"app {ReadLog.Keep + 4}", log.Entries[0].Target);
        log.Clear();
        Assert.Empty(log.Entries);
        Assert.Equal(ReadLog.Keep + 6, changes);
    }

    [Fact]
    public async Task Each_call_that_reaches_a_tool_is_noted()
    {
        var box = new Toolbox([
            new DeviceTool("file_read", "Read a file.", "files", 0, new JsonObject { ["type"] = "object" },
                (args, _) => args["path"]!.GetValue<string>().EndsWith(".txt")
                    ? Task.FromResult<JsonNode>(new JsonObject { ["text"] = "secret words" })
                    : throw new ToolFailure("not a text file")),
        ]) { Log = new ReadLog() };
        HashSet<string> files = ["files"];
        await box.CallAsync("file_read", new JsonObject { ["path"] = @"D:\a.txt" }, files, CancellationToken.None);
        await box.CallAsync("file_read", new JsonObject { ["path"] = @"D:\b.bin" }, files, CancellationToken.None);
        await box.CallAsync("file_read", new JsonObject { ["path"] = @"D:\c.txt" }, new HashSet<string>(), CancellationToken.None); // skill off
        Assert.Equal([@"Read a file: D:\b.bin (did not run)", @"Read a file: D:\a.txt"], box.Log!.Entries.Select(e => e.Line));
        Assert.DoesNotContain(box.Log.Entries, e => e.Line.Contains("secret"));
    }

    [Fact]
    public void Folders_inside_the_user_folder_narrow_Ira_and_folders_elsewhere_are_added()
    {
        using var home = new PretendHome();
        var report = Path.Combine(home.Home, @"Documents\report.txt");
        var invoice = Path.Combine(home.Home, @"Downloads\invoice.pdf.txt");

        var all = PathPolicy.ForFolders(home.Home, []);
        Assert.True(all.Allows(report) && all.Allows(invoice));
        Assert.Single(all.Roots);

        // A folder elsewhere (here in Temp, which Windows itself keeps under a hidden folder, so
        // only its place among the roots is checked).
        var outside = Path.Combine(Path.GetTempPath(), "ira-work-" + Guid.NewGuid().ToString("N")[..8]);
        var narrowed = PathPolicy.ForFolders(home.Home, [@"~\Documents", outside]);
        Assert.True(narrowed.Allows(report));
        Assert.False(narrowed.Allows(invoice));
        Assert.Equal(2, narrowed.Roots.Count);
        Assert.EndsWith(Path.GetFileName(outside), narrowed.Roots[1], StringComparison.OrdinalIgnoreCase);
        // The deny list still holds inside a chosen folder.
        Assert.False(PathPolicy.ForFolders(home.Home, [home.Home]).Allows(Path.Combine(home.Home, @"AppData\Roaming\secret.txt")));
    }

    [Fact]
    public void Preferences_round_trip_and_fall_back_to_the_defaults()
    {
        var path = Path.Combine(Path.GetTempPath(), $"ira-preferences-{Guid.NewGuid():N}.json");
        try
        {
            Assert.Equal("Ctrl+Alt+Space", PcPreferences.Load(path).Shortcut);
            new PcPreferences { Shortcut = "Ctrl+Alt+I", Folders = [@"D:\Work"] }.Save(path);
            var loaded = PcPreferences.Load(path);
            Assert.Equal(("Ctrl+Alt+I", 0x49u), (loaded.Shortcut, Shortcut.Named(loaded.Shortcut).Key));
            Assert.Equal([@"D:\Work"], loaded.Folders);

            File.WriteAllText(path, "{ not json");
            Assert.Empty(PcPreferences.Load(path).Folders);
            Assert.Equal(Shortcut.Default, Shortcut.Named("Win+Q"));
        }
        finally
        {
            File.Delete(path);
        }
    }
}
