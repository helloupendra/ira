using System.Text.Json.Nodes;
using IraKit;

namespace IraKit.Windows.Tests;

public class ToolboxAndEventTests
{
    private static readonly HashSet<string> FilesOnly = ["files"];

    private static Toolbox Box(Func<JsonObject, CancellationToken, Task<JsonNode>> run) => new([
        new DeviceTool("files_find", "Find files.", "files", 0, new JsonObject { ["type"] = "object" }, run),
        new DeviceTool("screen_read", "Read the front window.", "screen", 0, new JsonObject { ["type"] = "object" },
            (_, _) => Task.FromResult<JsonNode>(new JsonObject { ["summary"] = "read" })),
    ]);

    [Fact]
    public void The_hello_lists_each_tool_with_its_skill_and_tier()
    {
        var hello = Box((_, _) => Task.FromResult<JsonNode>(new JsonObject())).HelloTools();
        var first = hello.OfType<JsonObject>().Single(t => t["name"]!.GetValue<string>() == "files_find");
        Assert.Equal("files", first["skill"]!.GetValue<string>());
        Assert.Equal(0, first["tier"]!.GetValue<int>());
        Assert.Equal("object", first["parameters"]!["type"]!.GetValue<string>());
    }

    [Fact]
    public async Task A_call_runs_only_when_its_skill_is_on_on_this_PC()
    {
        var box = Box((_, _) => Task.FromResult<JsonNode>(new JsonObject { ["summary"] = "Found 2 files." }));
        var ok = await box.CallAsync("files_find", [], FilesOnly, CancellationToken.None);
        Assert.True(ok.Ok);
        Assert.Equal("Found 2 files.", ok.Content!["summary"]!.GetValue<string>());

        var off = await box.CallAsync("screen_read", [], FilesOnly, CancellationToken.None);
        Assert.False(off.Ok);
        Assert.Contains("screen skill is off on this PC", off.Error);

        var unknown = await box.CallAsync("shell_run", [], FilesOnly, CancellationToken.None);
        Assert.False(unknown.Ok);
    }

    [Fact]
    public async Task A_failure_says_its_words_but_a_crash_never_leaks_its_message()
    {
        var failing = Box((_, _) => throw new ToolFailure("there is no file at that path"));
        Assert.Equal("there is no file at that path",
            (await failing.CallAsync("files_find", [], FilesOnly, CancellationToken.None)).Error);

        var crashing = Box((_, _) => throw new InvalidOperationException(@"C:\Users\me\secret.txt is locked"));
        var crashed = await crashing.CallAsync("files_find", [], FilesOnly, CancellationToken.None);
        Assert.False(crashed.Ok);
        Assert.DoesNotContain("secret", crashed.Error);
    }

    [Fact]
    public void Each_streamed_event_is_read()
    {
        Assert.Equal(new AskEvent.Started("c1"), AskClient.Parse("""{"type":"start","conversation_id":"c1"}"""));
        Assert.Equal(new AskEvent.Delta("Hello"), AskClient.Parse("""{"type":"delta","text":"Hello"}"""));
        Assert.Equal(new AskEvent.ToolFinished("t1", "files_find", true),
            AskClient.Parse("""{"type":"tool_result","id":"t1","name":"files_find","ok":true,"result":"x","truncated":false}"""));
        var proposed = Assert.IsType<AskEvent.Proposed>(AskClient.Parse(
            """{"type":"action","action":{"id":"act_1","tool":"app_open","summary":"Open Notepad","status":"pending","tier":2,"expires_in":120,"can_approve":true,"can_confirm":true}}"""));
        Assert.Equal(("act_1", 2, true), (proposed.Action.Id, proposed.Action.Tier, proposed.Action.CanApprove));
        Assert.Equal(new AskEvent.Done("Hi.", "demo:router", "c1"),
            AskClient.Parse("""{"type":"done","text":"Hi.","model":"demo:router","conversation_id":"c1"}"""));
        Assert.Null(AskClient.Parse("""{"type":"something_new"}"""));
        Assert.Null(AskClient.Parse("not json"));
    }
}
