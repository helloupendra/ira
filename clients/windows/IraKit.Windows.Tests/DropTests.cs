using System.Text.Json.Nodes;
using IraKit;

namespace IraKit.Windows.Tests;

public class DropTests
{
    [Theory]
    [InlineData("plan.pdf", "plan.pdf")]
    [InlineData(@"..\..\Windows\evil.dll", "evil.dll")]
    [InlineData("a/b/c.txt", "c.txt")]
    [InlineData("what?<>|*.txt", "what.txt")]
    [InlineData("report.pdf. . ", "report.pdf")]
    [InlineData("CON.txt", "_CON.txt")]
    [InlineData(".hidden", "hidden")]
    [InlineData("", "file")]
    [InlineData("invoice.lnk", "invoice.lnk.download")]
    [InlineData("free-money.URL", "free-money.URL.download")]
    [InlineData("desktop.ini", "desktop.ini.download")]
    [InlineData("music.library-ms", "music.library-ms.download")]
    public void Names_are_safe_to_save(string given, string saved) => Assert.Equal(saved, Drop.SafeName(given));

    [Fact]
    public void A_file_never_lands_on_another()
    {
        var folder = Directory.CreateTempSubdirectory("ira-drop-").FullName;
        try
        {
            Assert.Equal(Path.Combine(folder, "plan.pdf"), Drop.FreePath(folder, "plan.pdf"));
            File.WriteAllText(Path.Combine(folder, "plan.pdf"), "1");
            File.WriteAllText(Path.Combine(folder, "plan (2).pdf"), "2");
            Assert.Equal(Path.Combine(folder, "plan (3).pdf"), Drop.FreePath(folder, "plan.pdf"));
        }
        finally
        {
            Directory.Delete(folder, true);
        }
    }

    [Fact]
    public void A_saved_file_is_marked_as_downloaded()
    {
        var file = Path.Combine(Path.GetTempPath(), $"ira-motw-{Guid.NewGuid():N}.pdf");
        File.WriteAllText(file, "x");
        try
        {
            Drop.MarkDownloaded(file, "https://ira.example.com");
            var zone = File.ReadAllText(file + ":Zone.Identifier");
            Assert.Contains("ZoneId=3", zone);
            Assert.Contains("HostUrl=https://ira.example.com", zone);
        }
        finally
        {
            File.Delete(file);
        }
    }

    [Fact]
    public void Frames_and_items_are_read()
    {
        var frame = JsonNode.Parse("""
            {"type":"drop","event":"new","item":{"id":7,"kind":"file","text":"for the  meeting","name":"plan.pdf",
             "mime":"application/pdf","size":2048,"sha256":"ab","from_device_id":3,"from_label":"Pixel",
             "created_at":"2026-10-30T10:00:00Z","expires_at":"2026-11-29T10:00:00Z"}}
            """)!;
        var item = Assert.IsType<DropFrame.New>(DropFrame.From(frame)).Item;
        Assert.Equal((7L, "Pixel", 3L), (item.Id, item.FromLabel, item.FromDeviceId!.Value));
        Assert.Equal("plan.pdf (2.0 KB): for the meeting", item.Preview);
        Assert.Equal(new DropFrame.Deleted(9), DropFrame.From(JsonNode.Parse("""{"type":"drop","event":"deleted","id":9}""")!));
        Assert.Null(DropFrame.From(JsonNode.Parse("""{"type":"drop","event":"new","item":{"id":1}}""")!));
    }

    [Theory]
    [InlineData("https://github.com/helloupendra/ira", true)]
    [InlineData("javascript:alert(1)", false)]
    [InlineData("file:///C:/Windows/notepad.exe", false)]
    [InlineData("https://a.com and more", false)]
    public void Only_web_links_open(string text, bool opens) =>
        Assert.Equal(opens, new DropItem(1, "link", text).Link is not null);
}
