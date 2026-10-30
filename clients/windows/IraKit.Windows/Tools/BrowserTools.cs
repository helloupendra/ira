using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Windows.Automation;

namespace IraKit.Tools;

/// <summary>
/// browser_tabs (Tier 0) and browser_show_tab (Tier 1), in the <c>browser</c> skill: the tabs
/// open in Chrome, Edge, Brave, Firefox, Vivaldi and Opera, read through UI Automation. Titles
/// for every tab and the address of each window's open tab; never what a page shows.
/// </summary>
internal static class BrowserTools
{
    /// <summary>Browser programs, by the name Ira uses for each.</summary>
    public static readonly Dictionary<string, string> Programs = new(StringComparer.OrdinalIgnoreCase)
    {
        ["chrome"] = "chrome",
        ["msedge"] = "edge",
        ["brave"] = "brave",
        ["vivaldi"] = "vivaldi",
        ["opera"] = "opera",
        ["firefox"] = "firefox",
        ["arc"] = "arc",
    };

    private static readonly string[] WindowClasses = ["Chrome_WidgetWin_1", "MozillaWindowClass"];

    public sealed record Tab(string Id, string Browser, int Window, string Title, string Url, bool Active)
    {
        internal AutomationElement? Element { get; init; }
        internal IntPtr Handle { get; init; }
    }

    public static IEnumerable<DeviceTool> Tools() =>
    [
        new("browser_tabs",
            "List the tabs open in the browsers on this PC (Chrome, Edge, Brave, Firefox, Vivaldi, Opera): each tab's title, "
            + "the address (without its query) of the tab that is open in each window, which is in front, and an id. "
            + "Only titles and addresses, never page contents. Use it for 'what is open in Chrome?'.",
            "browser", 0,
            Schema.Object(new JsonObject { ["browser"] = Schema.Text("Only this browser: chrome, edge, brave, firefox, vivaldi or opera.") }),
            (args, ct) => Task.Run(() => List(args, ct), ct)),
        new("browser_show_tab",
            "Bring one browser tab to the front, by words from its title or by its id from browser_tabs. To answer what a tab "
            + "shows ('how far is that upload?'), bring it to the front, then use screen_read. Say that you switched to it.",
            "browser", 1,
            Schema.Object(new JsonObject
            {
                ["match"] = Schema.Text("Words from the tab's title or address, e.g. 'upload' or 'github'."),
                ["id"] = Schema.Text("The tab's id from browser_tabs."),
                ["browser"] = Schema.Text("Only this browser: chrome, edge, brave, firefox, vivaldi or opera."),
            }),
            (args, ct) => Task.Run(() => Show(args, ct), ct)),
    ];

    private static JsonNode List(JsonObject raw, CancellationToken ct)
    {
        var args = new ToolArgs(raw, "browser");
        var tabs = Tabs(Browser(args), ct);
        var items = new JsonArray(tabs.Select(t => (JsonNode)new JsonObject
        {
            ["id"] = t.Id,
            ["browser"] = t.Browser,
            ["window"] = t.Window,
            ["title"] = t.Title,
            ["url"] = t.Url,
            ["active"] = t.Active,
        }).ToArray());
        string summary;
        if (tabs.Count == 0)
        {
            summary = "No browser tabs are open.";
        }
        else
        {
            var browsers = tabs.GroupBy(t => t.Browser).Select(g => $"{g.Count()} in {Name(g.Key)}");
            var front = tabs.Where(t => t.Active).Select(t => $"“{t.Title}”").Take(3);
            summary = $"{tabs.Count} tab{(tabs.Count == 1 ? "" : "s")} open: {string.Join(", ", browsers)}. In front: {string.Join(", ", front)}.";
        }
        return new JsonObject { ["tabs"] = items, ["count"] = tabs.Count, ["summary"] = summary };
    }

    private static JsonNode Show(JsonObject raw, CancellationToken ct)
    {
        var args = new ToolArgs(raw, "match", "id", "browser");
        var id = args.Text("id", 100);
        var match = args.Text("match", 200);
        if (id is null && match is null) throw new ToolFailure("say which tab: words from its title, or its id");
        var tabs = Tabs(Browser(args), ct);

        Tab? tab;
        if (id is not null)
        {
            tab = tabs.FirstOrDefault(t => t.Id == id)
                ?? throw new ToolFailure("that tab is no longer open where it was; list the tabs again");
        }
        else
        {
            var words = match!.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries);
            var found = tabs.Where(t => words.All(w => t.Title.Contains(w, StringComparison.OrdinalIgnoreCase)
                || t.Url.Contains(w, StringComparison.OrdinalIgnoreCase))).ToList();
            if (found.Count == 0) throw new ToolFailure($"no open tab matches “{match}”");
            tab = found[0];
        }

        Select(tab.Element!);
        Native.BringToFront(tab.Handle);
        return new JsonObject
        {
            ["tab"] = new JsonObject { ["title"] = tab.Title, ["browser"] = tab.Browser },
            ["summary"] = $"Switched to “{tab.Title}” in {Name(tab.Browser)}.",
        };
    }

    private static string? Browser(ToolArgs args)
    {
        var browser = args.Text("browser")?.ToLowerInvariant();
        if (browser is null) return null;
        if (browser is "microsoft edge") browser = "edge";
        if (browser is "google chrome") browser = "chrome";
        if (!Programs.ContainsValue(browser)) throw new ToolFailure("browser must be one of: chrome, edge, brave, firefox, vivaldi or opera");
        return browser;
    }

    public static string Name(string browser) => browser switch
    {
        "edge" => "Edge",
        "chrome" => "Chrome",
        _ => char.ToUpperInvariant(browser[0]) + browser[1..],
    };

    /// <summary>Every tab in every browser window (or one browser's), in window order.</summary>
    internal static List<Tab> Tabs(string? only, CancellationToken ct)
    {
        var tabs = new List<Tab>();
        var windowNumber = 0;
        foreach (AutomationElement window in AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition))
        {
            ct.ThrowIfCancellationRequested();
            string className;
            int pid;
            IntPtr handle;
            try
            {
                className = window.Current.ClassName;
                pid = window.Current.ProcessId;
                handle = new IntPtr(window.Current.NativeWindowHandle);
            }
            catch (ElementNotAvailableException)
            {
                continue;
            }
            if (!WindowClasses.Contains(className) || !Native.IsWindowVisible(handle)) continue;
            if (BrowserOf(pid) is not { } browser || only is not null && browser != only) continue;

            var (items, address) = Controls(window, ct);
            if (items.Count == 0) continue;
            windowNumber++;
            for (var i = 0; i < items.Count; i++)
            {
                var active = IsSelected(items[i]);
                tabs.Add(new Tab($"{browser}:{handle}:{i}", browser, windowNumber, items[i].Current.Name, active ? CleanUrl(address) : "", active)
                {
                    Element = items[i],
                    Handle = handle,
                });
            }
        }
        return tabs;
    }

    private static string? BrowserOf(int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return Programs.GetValueOrDefault(process.ProcessName);
        }
        catch (ArgumentException)
        {
            return null;
        }
    }

    /// <summary>
    /// The window's tabs and its address bar, found by walking the browser's own controls only:
    /// a page's content (its Document) is never entered, so it is never read and never slow.
    /// </summary>
    private static (List<AutomationElement> Tabs, string? Address) Controls(AutomationElement window, CancellationToken ct)
    {
        var walker = TreeWalker.ControlViewWalker;
        var tabs = new List<AutomationElement>();
        string? address = null;
        var queue = new Queue<(AutomationElement Element, int Depth)>();
        queue.Enqueue((window, 0));
        var visited = 0;
        while (queue.Count > 0 && visited < 3000)
        {
            ct.ThrowIfCancellationRequested();
            var (element, depth) = queue.Dequeue();
            visited++;
            ControlType type;
            try
            {
                type = element.Current.ControlType;
            }
            catch (ElementNotAvailableException)
            {
                continue;
            }
            if (type == ControlType.Document) continue;
            if (type == ControlType.TabItem)
            {
                tabs.Add(element);
                continue;
            }
            if (address is null && type == ControlType.Edit
                && element.TryGetCurrentPattern(ValuePattern.Pattern, out var value))
            {
                address = ((ValuePattern)value).Current.Value;
            }
            if (depth >= 14) continue;
            for (var child = walker.GetFirstChild(element); child is not null; child = walker.GetNextSibling(child))
                queue.Enqueue((child, depth + 1));
        }
        return (tabs, address);
    }

    private static bool IsSelected(AutomationElement tab) =>
        tab.TryGetCurrentPattern(SelectionItemPattern.Pattern, out var pattern) && ((SelectionItemPattern)pattern).Current.IsSelected;

    private static void Select(AutomationElement tab)
    {
        if (tab.TryGetCurrentPattern(SelectionItemPattern.Pattern, out var selection)) ((SelectionItemPattern)selection).Select();
        else if (tab.TryGetCurrentPattern(InvokePattern.Pattern, out var invoke)) ((InvokePattern)invoke).Invoke();
        else throw new ToolFailure("that browser did not let me switch tabs");
    }

    /// <summary>An address without its query or fragment ("github.com/a?x=1" becomes "https://github.com/a"); "" for search text.</summary>
    internal static string CleanUrl(string? text)
    {
        if (string.IsNullOrWhiteSpace(text) || text.Contains(' ')) return "";
        text = text.Trim();
        if (!text.Contains("://", StringComparison.Ordinal)) text = "https://" + text;
        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri) || uri.Host.Length == 0 || !uri.Host.Contains('.') && uri.Host != "localhost")
            return "";
        return $"{uri.Scheme}://{uri.Authority}{uri.AbsolutePath}".TrimEnd('/');
    }
}
