using System.Text.Json.Nodes;
using IraKit.Tools;
using Xunit.Abstractions;

namespace IraKit.Windows.Tests;

/// <summary>
/// The tools against this PC itself: the real Windows Search, browsers, window in front, Start
/// menu and clipboard. Only with IRA_LIVE_TESTS=1, and they print counts, never contents.
/// </summary>
[Trait("Category", "Live")]
public class LivePcToolsTests(ITestOutputHelper output)
{
    private static readonly HashSet<string> AllSkills = ["files", "screen", "browser", "apps", "clipboard"];
    private static bool Live => Environment.GetEnvironmentVariable("IRA_LIVE_TESTS") == "1";

    private static async Task<(bool Ok, JsonNode? Content, string? Error)> Call(string tool, JsonObject args) =>
        await PcTools.Create(Native.GetForegroundWindow).CallAsync(tool, args, AllSkills, CancellationToken.None);

    [Fact]
    public async Task Windows_Search_finds_recent_documents()
    {
        if (!Live) return;
        var (ok, content, error) = await Call("files_find", new JsonObject { ["kind"] = "document", ["modifiedWithinDays"] = 365 });
        Assert.True(ok, error);
        var summary = content!["summary"]!.GetValue<string>();
        output.WriteLine($"files_find: {content["count"]} results; by name only: {summary.Contains("by name only")}");
        Assert.All(content["results"]!.AsArray(), r => Assert.DoesNotContain(@"\AppData\", r!["path"]!.GetValue<string>(), StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Browser_tabs_are_listed()
    {
        if (!Live) return;
        var (ok, content, error) = await Call("browser_tabs", []);
        Assert.True(ok, error);
        var tabs = content!["tabs"]!.AsArray();
        var active = tabs.Count(t => t!["active"]!.GetValue<bool>());
        var withAddress = tabs.Count(t => t!["url"]!.GetValue<string>().Length > 0);
        output.WriteLine($"browser_tabs: {tabs.Count} tabs, {active} in front, {withAddress} with an address; browsers: "
            + string.Join(", ", tabs.Select(t => t!["browser"]!.GetValue<string>()).Distinct()));
    }

    [Fact]
    public async Task The_window_in_front_is_read()
    {
        if (!Live) return;
        var (ok, content, error) = await Call("screen_read", []);
        output.WriteLine(ok ? $"screen_read: {content!["app"]} gave {content["chars"]} characters" : $"screen_read refused: {error}");
        Assert.True(ok, error);
    }

    [Fact]
    public void The_Start_menu_lists_apps_and_marks_the_shells()
    {
        if (!Live) return;
        var apps = AppTools.StartMenuApps();
        var never = apps.Where(AppTools.IsNever).Select(a => a.Name).Distinct().Order().ToList();
        output.WriteLine($"Start menu: {apps.Count} apps; never opened: {string.Join(", ", never)}");
        Assert.NotEmpty(apps);
    }

    [Fact]
    public async Task The_clipboard_is_read()
    {
        if (!Live) return;
        var (ok, content, error) = await Call("clipboard_read", []);
        output.WriteLine(ok ? $"clipboard_read: {(content!["text"] is { } text ? $"{text.GetValue<string>().Length} characters" : content["summary"])}" : $"refused: {error}");
        Assert.True(ok || error!.Contains("private"), error);
    }
}
