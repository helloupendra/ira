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

    [Theory]
    // Start, as the Windows key: "ctrl+esc c m d enter" would open a Command Prompt.
    [InlineData("ctrl+esc")]
    [InlineData("ctrl+esc c m d enter")]
    [InlineData("alt+esc")]
    // Any Ctrl+Alt shortcut: Windows and other apps take them everywhere.
    [InlineData("ctrl+alt+t")]
    // Ira's own: every panel shortcut Settings offers, and Drop's send and copy.
    [InlineData("ctrl+alt+space")]
    [InlineData("ctrl+shift+space")]
    [InlineData("alt+shift+space")]
    [InlineData("ctrl+alt+i")]
    [InlineData("ctrl+alt+shift+v")]
    [InlineData("ctrl+alt+shift+c")]
    [InlineData("down shift+alt+space")]
    public void Shortcuts_that_act_outside_the_window_are_refused(string keys) =>
        Assert.Contains("I never press", Assert.Throws<ToolFailure>(() => ControlTools.Keyboard.Parse(keys)).Message);

    [Theory]
    [InlineData("esc")]
    [InlineData("ctrl+shift+t")]
    [InlineData("shift+tab")]
    [InlineData("alt+f")]
    [InlineData("ctrl+space")]
    [InlineData("shift+space")]
    public void Shortcuts_inside_the_window_still_work(string keys) => Assert.Single(ControlTools.Keyboard.Parse(keys));

    [Fact]
    public void Keys_stop_when_a_press_moved_the_keyboard_elsewhere()
    {
        IntPtr app = 10, dialog = 11, start = 12;
        Assert.Null(ControlTools.Moved(app, app, 5, 5, null));
        // A dialog the app itself opened (Save as, say) is still the app.
        Assert.Null(ControlTools.Moved(dialog, app, 5, 5, null));
        Assert.Equal("another app took the keyboard", ControlTools.Moved(start, app, 9, 5, null));
        Assert.Equal("Ira doesn't act there", ControlTools.Moved(dialog, app, 5, 5, "I never act in File Explorer"));
        Assert.Equal("nothing is in front", ControlTools.Moved(IntPtr.Zero, app, 0, 5, null));
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
    public void The_PC_refuses_Explorer_the_Run_box_editors_with_a_terminal_and_REPLs()
    {
        static WindowInfo Window(string program, string app, string className = "") => new(IntPtr.Zero, program, app, "", className);
        // Their address bar runs what is typed.
        Assert.Contains("File Explorer", ControlTools.Refusal(Window("explorer.exe", "Windows Explorer", "CabinetWClass")));
        Assert.Contains("Run box", ControlTools.Refusal(Window("explorer.exe", "Windows Explorer", "#32770")));
        // ctrl+` opens a terminal; Python's and Node's own windows run each line.
        foreach (var (program, app) in new[] { ("code.exe", "Visual Studio Code"), ("cursor.exe", "Cursor"), ("idea64.exe", "IntelliJ IDEA"),
                                               ("python.exe", "Python"), ("pythonw.exe", "IDLE"), ("node.exe", "Node.js") })
        {
            Assert.Contains("terminals", ControlTools.Refusal(Window(program, app)));
        }
        Assert.Null(ControlTools.Refusal(Window("notepad.exe", "Notepad")));
        Assert.Null(ControlTools.Refusal(Window("winword.exe", "Word")));
    }

    [Fact]
    public void The_PC_never_acts_in_Iras_own_windows()
    {
        // Its approval cards and skill switches: a click there would say yes for the person.
        var own = new WindowInfo(IntPtr.Zero, "ira.exe", "Ira", "Ira", "");
        Assert.Contains("Ira's own", ControlTools.Refusal(own, (uint)Environment.ProcessId));
        Assert.Null(ControlTools.Refusal(new WindowInfo(IntPtr.Zero, "notepad.exe", "Notepad", "", ""), (uint)Environment.ProcessId + 1));
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
