using System.Diagnostics;
using IraKit.Tools;

namespace IraKit.Windows.Tests;

/// <summary>A pretend user folder in Temp, with the places Ira must never read.</summary>
public sealed class PretendHome : IDisposable
{
    public string Home { get; } = Path.Combine(Path.GetTempPath(), "ira-home-" + Guid.NewGuid().ToString("N")[..8]);

    public PretendHome()
    {
        Write(@"Documents\report.txt", "quarterly report");
        Write(@"AppData\Roaming\secret.txt", "saved password");
        Write(@".ssh\id_ed25519", "private key");
        Write(@"Downloads\server.pem", "key");
        Write(@"Downloads\.env.local", "TOKEN=x");
        Write(@"Downloads\invoice.pdf.txt", "invoice 42");
        Write(@"Private\diary.txt", "hidden");
        File.SetAttributes(Path.Combine(Home, "Private"), FileAttributes.Directory | FileAttributes.Hidden);
        // A junction on the Desktop that leads into AppData: as bad as AppData itself.
        Directory.CreateDirectory(Path.Combine(Home, "Desktop"));
        Run("cmd.exe", "/c", "mklink", "/J", Path.Combine(Home, @"Desktop\shortcut"), Path.Combine(Home, @"AppData\Roaming"));
    }

    public string Write(string relative, string text)
    {
        var path = Path.Combine(Home, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, text);
        return path;
    }

    private static void Run(string program, params string[] args)
    {
        var start = new ProcessStartInfo(program) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        using var process = Process.Start(start)!;
        process.WaitForExit();
    }

    public void Dispose()
    {
        try
        {
            var junction = Path.Combine(Home, @"Desktop\shortcut");
            if (Directory.Exists(junction)) Directory.Delete(junction); // the link, not what it leads to
            File.SetAttributes(Path.Combine(Home, "Private"), FileAttributes.Directory);
            Directory.Delete(Home, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}

public sealed class PathPolicyTests : IDisposable
{
    private readonly PretendHome _home = new();
    private readonly PathPolicy _policy;

    public PathPolicyTests() => _policy = new PathPolicy(_home.Home);

    public void Dispose() => _home.Dispose();

    [Theory]
    [InlineData(@"~\Documents\report.txt")]
    [InlineData(@"~/Documents/report.txt")]
    [InlineData(@"~\Downloads\invoice.pdf.txt")]
    [InlineData(@"~\Documents\not-there-yet.txt")]
    public void Files_in_the_user_folder_are_allowed(string path) => Assert.Null(_policy.Refusal(path));

    [Fact]
    public void A_full_path_is_allowed_in_any_case() =>
        Assert.Null(_policy.Refusal(Path.Combine(_home.Home, "DOCUMENTS", "Report.TXT")));

    [Theory]
    [InlineData(@"~\AppData\Roaming\secret.txt", "AppData")]
    [InlineData(@"~\appdata\roaming\secret.txt", "AppData")]
    [InlineData(@"~\.ssh\id_ed25519", "AppData|hidden|.ssh")]
    [InlineData(@"~\Downloads\server.pem", "key")]
    [InlineData(@"~\Downloads\server.pem.", "key")]
    [InlineData(@"~\Downloads\server.pem .", "key")]
    [InlineData(@"~\Downloads\.env.local", "hidden|passwords")]
    [InlineData(@"~\Private\diary.txt", "hidden")]
    [InlineData(@"~\Desktop\shortcut\secret.txt", "AppData")]
    public void Secrets_hidden_places_and_links_to_them_are_refused(string path, string why)
    {
        var refusal = _policy.Refusal(path);
        Assert.NotNull(refusal);
        Assert.Matches(why, refusal);
    }

    [Theory]
    [InlineData(@"\\server\share\file.txt")]
    [InlineData(@"\\?\C:\Windows\win.ini")]
    [InlineData(@"\\.\PhysicalDrive0")]
    [InlineData(@"Documents\report.txt")]
    [InlineData(@"C:Documents\report.txt")]
    [InlineData(@"~\Documents\report.txt:hidden")]
    [InlineData(@"~\Documents\*.txt")]
    public void Odd_paths_are_refused(string path) => Assert.Contains("give the full path", _policy.Refusal(path));

    [Theory]
    [InlineData(@"C:\Windows\win.ini")]
    [InlineData(@"~\..\..\..\..\..\..\..\..\Windows\win.ini")]
    [InlineData(@"C:\Program Files\desktop.txt")]
    public void Windows_own_folders_are_refused(string path) =>
        Assert.Contains("Windows' own folders", _policy.Refusal(path));

    [Fact]
    public void A_folder_inside_a_hidden_one_is_refused_even_when_added()
    {
        // Temp lives in AppData, which Windows hides.
        var inTemp = Path.Combine(Path.GetTempPath(), "notes.txt");
        Assert.Contains("hidden", new PathPolicy(_home.Home, extra: [Path.GetTempPath()]).Refusal(inTemp));
    }

    [Fact]
    public void Elsewhere_on_the_disk_is_outside_unless_added()
    {
        // In the real user folder (not Temp, which is hidden), and gone again after.
        var elsewhere = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "ira-test-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(elsewhere);
        try
        {
            var file = Path.Combine(elsewhere, "notes.txt");
            Assert.Contains("outside the folders", _policy.Refusal(file));
            Assert.Null(new PathPolicy(_home.Home, extra: [elsewhere]).Refusal(file));
        }
        finally
        {
            Directory.Delete(elsewhere, true);
        }
    }

    [Fact]
    public void Chosen_folders_narrow_the_search()
    {
        var narrow = new PathPolicy(_home.Home, only: [@"~\Documents"]);
        Assert.Null(narrow.Refusal(@"~\Documents\report.txt"));
        Assert.Contains("outside the folders", narrow.Refusal(@"~\Downloads\invoice.pdf.txt"));
    }

    [Fact]
    public void Paths_are_shown_from_the_user_folder() =>
        Assert.Equal(@"~\Documents\report.txt", _policy.Display(PathPolicy.Resolve(Path.Combine(_home.Home, @"Documents\report.txt"))));
}
