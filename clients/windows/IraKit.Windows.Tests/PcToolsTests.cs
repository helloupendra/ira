using System.IO.Compression;
using System.Text.Json.Nodes;
using IraKit.Tools;
using UglyToad.PdfPig.Content;
using UglyToad.PdfPig.Core;
using UglyToad.PdfPig.Fonts.Standard14Fonts;
using UglyToad.PdfPig.Writer;

namespace IraKit.Windows.Tests;

public sealed class PcToolsTests : IDisposable
{
    private static readonly HashSet<string> AllSkills = ["files", "screen", "browser", "apps", "clipboard"];
    private readonly PretendHome _home = new();
    private readonly Toolbox _box;

    public PcToolsTests() => _box = PcTools.Create(() => IntPtr.Zero, () => new PathPolicy(_home.Home));

    public void Dispose() => _home.Dispose();

    private async Task<JsonNode> Ok(string tool, JsonObject args)
    {
        var (ok, content, error) = await _box.CallAsync(tool, args, AllSkills, CancellationToken.None);
        Assert.True(ok, error);
        return content!;
    }

    private async Task<string> Refused(string tool, JsonObject args)
    {
        var (ok, _, error) = await _box.CallAsync(tool, args, AllSkills, CancellationToken.None);
        Assert.False(ok);
        return error!;
    }

    [Fact]
    public void The_hello_offers_the_Macs_tools_with_the_same_skills_and_tiers()
    {
        var tools = _box.HelloTools().OfType<JsonObject>()
            .ToDictionary(t => t["name"]!.GetValue<string>(), t => (t["skill"]!.GetValue<string>(), t["tier"]!.GetValue<int>()));
        Assert.Equal(new Dictionary<string, (string, int)>
        {
            ["files_find"] = ("files", 0),
            ["file_read"] = ("files", 0),
            ["file_open"] = ("files", 1),
            ["screen_read"] = ("screen", 0),
            ["browser_tabs"] = ("browser", 0),
            ["browser_show_tab"] = ("browser", 1),
            ["app_open"] = ("apps", 1),
            ["url_open"] = ("apps", 2),
            ["clipboard_read"] = ("clipboard", 0),
        }, tools);
    }

    [Fact]
    public async Task Unknown_arguments_are_refused() =>
        Assert.Contains("unknown argument(s): shell", await Refused("file_read", new JsonObject { ["path"] = "~", ["shell"] = "x" }));

    [Fact]
    public async Task A_text_file_is_read_and_a_key_file_is_not()
    {
        var read = await Ok("file_read", new JsonObject { ["path"] = @"~\Documents\report.txt" });
        Assert.Equal("quarterly report", read["text"]!.GetValue<string>());
        Assert.Equal("Read report.txt (text).", read["summary"]!.GetValue<string>());

        Assert.Contains("AppData", await Refused("file_read", new JsonObject { ["path"] = @"~\Desktop\shortcut\secret.txt" }));
        Assert.Contains("key", await Refused("file_read", new JsonObject { ["path"] = @"~\Downloads\server.pem" }));
    }

    [Fact]
    public async Task Long_text_is_cut_and_says_so()
    {
        _home.Write(@"Documents\long.md", string.Join(" ", Enumerable.Repeat("word", 2000)));
        var read = await Ok("file_read", new JsonObject { ["path"] = @"~\Documents\long.md", ["maxChars"] = 300 });
        Assert.True(read["truncated"]!.GetValue<bool>());
        Assert.True(read["chars"]!.GetValue<int>() <= 300);
        Assert.Equal("Markdown", read["kind"]!.GetValue<string>());
    }

    [Fact]
    public async Task A_PDF_is_read_with_its_page_count()
    {
        var builder = new PdfDocumentBuilder();
        var font = builder.AddStandard14Font(Standard14Font.Helvetica);
        builder.AddPage(PageSize.A4).AddText("Invoice 42 for Northgate", 12, new PdfPoint(40, 700), font);
        builder.AddPage(PageSize.A4).AddText("Total due 1,250", 12, new PdfPoint(40, 700), font);
        File.WriteAllBytes(Path.Combine(_home.Home, @"Documents\invoice.pdf"), builder.Build());

        var read = await Ok("file_read", new JsonObject { ["path"] = @"~\Documents\invoice.pdf" });
        Assert.Contains("Invoice 42 for Northgate", read["text"]!.GetValue<string>());
        Assert.Contains("Total due 1,250", read["text"]!.GetValue<string>());
        Assert.Equal(2, read["pages"]!.GetValue<int>());
    }

    [Fact]
    public async Task A_Word_file_is_read_paragraph_by_paragraph()
    {
        var path = Path.Combine(_home.Home, @"Documents\letter.docx");
        using (var zip = ZipFile.Open(path, ZipArchiveMode.Create))
        using (var writer = new StreamWriter(zip.CreateEntry("word/document.xml").Open()))
        {
            writer.Write("""
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
                <w:p><w:r><w:t>Dear Sam,</w:t></w:r></w:p>
                <w:p><w:r><w:t xml:space="preserve">The boiler </w:t></w:r><w:r><w:t>is fixed.</w:t></w:r><w:r><w:tab/><w:t>Ok</w:t></w:r></w:p>
                </w:body></w:document>
                """);
        }
        var read = await Ok("file_read", new JsonObject { ["path"] = @"~\Documents\letter.docx" });
        Assert.Equal("Dear Sam,\nThe boiler is fixed.\tOk", read["text"]!.GetValue<string>());
        Assert.Equal("Word document", read["kind"]!.GetValue<string>());
    }

    [Fact]
    public void RTF_markup_is_dropped_and_its_characters_kept()
    {
        const string rtf = @"{\rtf1\ansi{\fonttbl{\f0 Calibri;}}{\colortbl;\red0\green0\blue0;}{\*\generator Word;}"
            + @"\f0 Caf\'e9 bill\par Total \u8212? paid\tab ok\par}";
        Assert.Equal("Café bill\nTotal — paid\tok\n", FileText.Rtf(rtf));
    }

    [Fact]
    public async Task Binary_files_and_unknown_kinds_are_not_read()
    {
        File.WriteAllBytes(Path.Combine(_home.Home, @"Documents\data.txt"), [0x50, 0x4B, 0x00, 0x01, 0x02]);
        Assert.Contains("not text", await Refused("file_read", new JsonObject { ["path"] = @"~\Documents\data.txt" }));
        _home.Write(@"Documents\tool.exe", "MZ");
        Assert.Contains("I can read PDF", await Refused("file_read", new JsonObject { ["path"] = @"~\Documents\tool.exe" }));
    }

    [Fact]
    public async Task Programs_scripts_and_links_are_never_opened()
    {
        foreach (var name in new[] { "setup.exe", "run.ps1", "go.bat", "x.lnk", "site.url", "fix.reg", "app.msix", "page.hta" })
        {
            _home.Write($@"Downloads\{name}", "x");
            Assert.Contains("never open", await Refused("file_open", new JsonObject { ["path"] = $@"~\Downloads\{name}" }));
        }
        Assert.Contains("nothing at that path", await Refused("file_open", new JsonObject { ["path"] = @"~\Downloads\gone.pdf" }));
    }

    [Fact]
    public async Task Finding_outside_the_allowed_folders_is_refused() =>
        Assert.Contains("Windows' own folders", await Refused("files_find", new JsonObject { ["folder"] = @"C:\Windows" }));

    [Fact]
    public void The_walk_finds_files_by_name_and_never_in_denied_places()
    {
        var policy = new PathPolicy(_home.Home);
        var found = FileSearch.Walk(new FileSearch.Query(["secret"], null, null, null), [_home.Home], policy, CancellationToken.None);
        Assert.Empty(found); // AppData\Roaming\secret.txt, and through the Desktop junction
        found = FileSearch.Walk(new FileSearch.Query(["invoice"], "text", 7, null), [_home.Home], policy, CancellationToken.None);
        Assert.Equal("invoice.pdf.txt", Path.GetFileName(Assert.Single(found).Path));
    }

    [Fact]
    public void Search_words_carry_no_quotes_or_wildcards_into_the_query()
    {
        Assert.Equal(["invoice", "OR", "x", "x", "2024"], FileSearch.Words("invoice' OR 'x'='x\" 2024"));
        Assert.Equal(["a", "b", "c", "d", "e", "f"], FileSearch.Words("a b c d e f g h"));

        var sql = FileSearch.Sql(new FileSearch.Query(["it's", "rent%"], "pdf", 2, null),
            [@"C:\Users\Sam O'Neil"], new DateTime(2026, 10, 30, 12, 0, 0, DateTimeKind.Utc), 100);
        Assert.Contains("SCOPE='file:C:/Users/Sam O''Neil'", sql);
        Assert.Contains("System.FileExtension = '.pdf'", sql);
        Assert.Contains("System.DateModified >= '2026/10/28 12:00:00'", sql);
        Assert.StartsWith("SELECT TOP 100 ", sql);
    }

    [Fact]
    public void An_app_is_picked_by_name_and_shells_never_are()
    {
        AppTools.App[] apps =
        [
            new("Visual Studio Code", "Microsoft.VisualStudioCode"),
            new("Visual Studio 2022", "VisualStudio.abc"),
            new("Calculator", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
            new("Windows Terminal", "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App"),
            new("Ubuntu", "CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc!ubuntu"),
        ];
        Assert.Equal("Calculator", AppTools.Pick("calculator", apps).Name);
        Assert.Equal("Visual Studio Code", AppTools.Pick("visual studio code", apps).Name);
        Assert.Contains("several apps match", Assert.Throws<ToolFailure>(() => AppTools.Pick("visual studio", apps)).Message);
        Assert.Contains("no app called", Assert.Throws<ToolFailure>(() => AppTools.Pick("photoshop", apps)).Message);
        Assert.True(AppTools.IsNever(apps[3]));
        Assert.True(AppTools.IsNever(apps[4]));
        Assert.True(AppTools.IsNever(new("Developer PowerShell for VS 2022", "x")));
        Assert.False(AppTools.IsNever(apps[2]));
    }

    [Fact]
    public async Task Only_web_addresses_open_in_the_browser()
    {
        Assert.Equal("https://github.com/a?b=1", AppTools.WebUrl("github.com/a?b=1")!.AbsoluteUri);
        foreach (var bad in new[] { "file:///C:/Windows/notepad.exe", "javascript:alert(1)", "ms-settings:privacy", "https://user:pw@example.com" })
            Assert.Null(AppTools.WebUrl(bad));
        Assert.Contains("only web addresses", await Refused("url_open", new JsonObject { ["url"] = @"C:\Windows\System32\cmd.exe" }));
        Assert.Contains("never open terminals", await Refused("app_open", new JsonObject { ["name"] = "PowerShell" }));
    }

    [Fact]
    public void Tab_addresses_lose_their_query()
    {
        Assert.Equal("https://github.com/helloupendra/ira", BrowserTools.CleanUrl("github.com/helloupendra/ira?tab=readme#top"));
        Assert.Equal("http://localhost:8765/console", BrowserTools.CleanUrl("http://localhost:8765/console?x=1"));
        Assert.Equal("", BrowserTools.CleanUrl("best boiler brands"));
        Assert.Equal("", BrowserTools.CleanUrl(null));
    }

    [Fact]
    public void Password_managers_and_the_shell_are_not_read_from_the_screen()
    {
        Assert.Contains("can show passwords", ScreenTools.Refusal(new(IntPtr.Zero, "keepassxc.exe", "KeePassXC", "Vault", "Qt")));
        Assert.Contains("can show passwords", ScreenTools.Refusal(new(IntPtr.Zero, "credentialuibroker.exe", "Credential", "", "x")));
        Assert.Contains("taskbar", ScreenTools.Refusal(new(IntPtr.Zero, "explorer.exe", "Windows Explorer", "", "Shell_TrayWnd")));
        Assert.Null(ScreenTools.Refusal(new(IntPtr.Zero, "explorer.exe", "Windows Explorer", "Downloads", "CabinetWClass")));
        Assert.Null(ScreenTools.Refusal(new(IntPtr.Zero, "chrome.exe", "Google Chrome", "Inbox", "Chrome_WidgetWin_1")));
    }

    [Fact]
    public void Text_is_cut_at_a_word_end()
    {
        var cut = FileText.Cut("alpha beta gamma delta", "text", 12);
        Assert.Equal("alpha beta", cut.Text);
        Assert.True(cut.Truncated);
        Assert.Equal("ok", FileText.Cut("  ok\r\n", "text", 10).Text);
    }
}
