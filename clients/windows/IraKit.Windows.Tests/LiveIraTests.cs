using System.Diagnostics;
using System.Net;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using IraKit;
using Xunit.Abstractions;

namespace IraKit.Windows.Tests;

/// <summary>
/// The whole way against a real Ira: a throwaway server in a temporary folder, a pairing code
/// from <c>ira device code</c>, pairing, the device connection and a streamed answer.
/// Runs only with <c>IRA_LIVE_TESTS=1</c>, and needs <c>ira</c> (the repository's .venv, or
/// <c>IRA_EXE</c>).
/// </summary>
[Trait("Category", "Live")]
public partial class LiveIraTests(ITestOutputHelper output)
{
    private const string Password = "a-long-test-password-1"; // pragma: allowlist secret

    [Fact]
    public async Task A_Windows_PC_pairs_connects_and_gets_an_answer()
    {
        if (Environment.GetEnvironmentVariable("IRA_LIVE_TESTS") != "1")
        {
            output.WriteLine("Skipped: set IRA_LIVE_TESTS=1 to run against a real Ira.");
            return;
        }
        var ira = Environment.GetEnvironmentVariable("IRA_EXE") ?? FindIra();
        var folder = Directory.CreateTempSubdirectory("ira-live-").FullName;
        var port = FreePort();
        Process? server = null;
        try
        {
            Run(ira, folder, "init", folder, "--business", "a test", "--port", port.ToString());
            server = Start(ira, folder, "serve");
            var setupCode = await WaitForLine(server, SetupCode(), TimeSpan.FromSeconds(60));
            var address = ServerAddress.Parse($"http://127.0.0.1:{port}");
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };

            using (var setup = new HttpRequestMessage(HttpMethod.Post, address.Api("/v1/setup/owner"))
            {
                Content = JsonContent.Create(new { code = setupCode, email = "owner@example.com", password = Password }),
            })
            {
                setup.Headers.Add("X-Ira-Request", "1");
                var made = await http.SendAsync(setup);
                Assert.Equal(HttpStatusCode.OK, made.StatusCode);
            }

            var printed = Run(ira, folder, "device", "code", "--email", "owner@example.com", "--kind", "windows",
                "--days", "1", "--uses", "1", "--skills", "files");
            var link = PairingLink.Find(printed);
            Assert.NotNull(link?.Server);

            var paired = await Pairing.PairAsync(http, link!.Server!, link.Code);
            Assert.Equal("windows", paired.Kind);
            Assert.StartsWith("irad_", paired.Token);
            Assert.Equal(["files"], paired.Skills);

            var toolbox = new Toolbox([
                new DeviceTool("files_find", "Find files.", "files", 0, new JsonObject { ["type"] = "object" },
                    (_, _) => Task.FromResult<JsonNode>(new JsonObject { ["summary"] = "Found nothing." })),
            ]);
            var connection = new DeviceConnection(address, paired.Token, "Test PC", "0.1.0", toolbox,
                () => new HashSet<string> { "files" });
            var welcomed = new TaskCompletionSource<Welcome>();
            connection.Welcomed += w => welcomed.TrySetResult(w);
            using var stop = new CancellationTokenSource();
            var running = connection.RunAsync(stop.Token);
            var welcome = await welcomed.Task.WaitAsync(TimeSpan.FromSeconds(20));
            Assert.Equal(["files"], welcome.Skills);
            Assert.Equal(["files"], connection.EffectiveSkills);

            var ask = new AskClient(http, address, paired.Token);
            var events = new List<AskEvent>();
            await foreach (var e in ask.AskAsync("hello", null)) events.Add(e);
            output.WriteLine(string.Join("\n", events));
            Assert.IsType<AskEvent.Started>(events.First());
            Assert.IsType<AskEvent.Done>(events.Last());

            // Ira calls the PC's own tool over the device connection, and hears its answer.
            events.Clear();
            await foreach (var e in ask.AskAsync("files find report", null)) events.Add(e);
            output.WriteLine(string.Join("\n", events));
            Assert.Contains(events, e => e is AskEvent.ToolFinished { Name: "files_find", Ok: true });

            await stop.CancelAsync();
            await running.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally
        {
            if (server is { HasExited: false }) server.Kill(entireProcessTree: true);
            server?.WaitForExit(10_000);
            try { Directory.Delete(folder, recursive: true); } catch (IOException) { }
        }
    }

    private static string FindIra()
    {
        // From .../clients/windows/IraKit.Windows.Tests/bin/Debug/<tfm>/ up to the repository.
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "pyproject.toml"))) dir = dir.Parent;
        var exe = dir is null ? null : Path.Combine(dir.FullName, ".venv", "Scripts", "ira.exe");
        return exe is not null && File.Exists(exe) ? exe : throw new InvalidOperationException("Set IRA_EXE to the ira command.");
    }

    private static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private static ProcessStartInfo Info(string ira, string folder, string[] args)
    {
        var info = new ProcessStartInfo(ira) { WorkingDirectory = folder, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var a in args) info.ArgumentList.Add(a);
        info.Environment["PYTHONUNBUFFERED"] = "1";
        info.Environment["PYTHONUTF8"] = "1";
        return info;
    }

    private static string Run(string ira, string folder, params string[] args)
    {
        using var p = Process.Start(Info(ira, folder, args))!;
        var stdout = p.StandardOutput.ReadToEnd();
        var stderr = p.StandardError.ReadToEnd();
        p.WaitForExit();
        Assert.True(p.ExitCode == 0, $"ira {string.Join(' ', args)} failed: {stderr}");
        return stdout;
    }

    private static Process Start(string ira, string folder, params string[] args) => Process.Start(Info(ira, folder, args))!;

    private static async Task<string> WaitForLine(Process process, Regex pattern, TimeSpan limit)
    {
        using var timeout = new CancellationTokenSource(limit);
        while (await process.StandardOutput.ReadLineAsync(timeout.Token) is { } line)
        {
            if (pattern.Match(line) is { Success: true } m) return m.Groups[1].Value;
        }
        throw new InvalidOperationException("ira serve ended without printing a setup code");
    }

    [GeneratedRegex(@"setup code ([A-Z0-9-]{8,})")]
    private static partial Regex SetupCode();
}
