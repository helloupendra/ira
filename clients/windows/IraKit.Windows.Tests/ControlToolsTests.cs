using IraKit;
using IraKit.Tools;

namespace IraKit.Windows.Tests;

public class ControlToolsTests
{
    [Fact]
    public void Control_is_Tier_3_and_each_step_names_its_app_and_task()
    {
        var tools = new ControlTools(() => IntPtr.Zero).Tools().ToList();
        Assert.Equal(["pc_type", "pc_keys", "pc_click", "pc_scroll"], tools.Select(t => t.Name));
        Assert.All(tools, t => Assert.Equal(("control", 3), (t.Skill, t.Tier)));
        Assert.All(tools, t => Assert.NotNull(t.Parameters["properties"]!["task"]));
        Assert.All(tools, t => Assert.NotNull(t.Parameters["properties"]!["app"]));
    }

    [Fact]
    public void Keys_parse_and_the_ones_that_reach_a_command_are_refused()
    {
        var presses = ControlTools.Keyboard.Parse("ctrl+l down down enter F5");
        Assert.Equal(5, presses.Count);
        Assert.Equal([ControlTools.Keyboard.VK_CONTROL], presses[0].Modifiers);
        Assert.Equal((ushort)'L', presses[0].Key);
        Assert.Equal((ushort)0x74, presses[4].Key);
        foreach (var refused in new[] { "win+r", "cmd+space", "ctrl+shift+esc", "ctrl+alt+delete", "alt+tab", "win", "hyper+x", "launch" })
        {
            Assert.Throws<ToolFailure>(() => ControlTools.Keyboard.Parse(refused));
        }
        Assert.Throws<ToolFailure>(() => ControlTools.Keyboard.Parse(string.Join(' ', Enumerable.Repeat("down", 13))));
    }

    [Fact]
    public void The_PC_refuses_terminals_Task_Manager_and_password_managers_by_program()
    {
        static WindowInfo Window(string program, string app, string title = "") => new(IntPtr.Zero, program, app, title, "");
        Assert.Contains("terminals", ControlTools.Refusal(Window("windowsterminal.exe", "Windows Terminal")));
        Assert.Contains("terminals", ControlTools.Refusal(Window("taskmgr.exe", "Task Manager")));
        Assert.Contains("terminals", ControlTools.Refusal(Window("cmd.exe", "Windows Command Processor")));
        Assert.Contains("1Password", ControlTools.Refusal(Window("1password.exe", "1Password")));
        Assert.Contains("administrator", ControlTools.Refusal(Window("consent.exe", "Consent UI")));
        // A page about bash is still the browser.
        Assert.Null(ControlTools.Refusal(Window("chrome.exe", "Google Chrome", "Bash scripting - YouTube")));
    }

    [Fact]
    public void What_I_read_says_where_Ira_typed_never_what()
    {
        var target = ReadLog.Target("pc_type", new() { ["text"] = "my secret note", ["app"] = "notepad" },
            new System.Text.Json.Nodes.JsonObject { ["app"] = "notepad.exe" });
        Assert.Equal("14 characters in notepad.exe", target);
        Assert.Equal("“Search” in chrome.exe", ReadLog.Target("pc_click", new() { ["label"] = "Search", ["app"] = "chrome.exe" }));
    }
}
