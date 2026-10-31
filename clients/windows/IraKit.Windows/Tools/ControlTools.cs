using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using System.Windows.Automation;

namespace IraKit.Tools;

/// <summary>
/// pc_type, pc_keys, pc_click and pc_scroll (Tier 3), in the <c>control</c> skill: use this PC
/// like a person, in the window the person is in or in an app they name, each step after the
/// PIN or within an approval it opened. The PC refuses, whatever the server asks: terminals,
/// shells, Task Manager and script hosts (by program file), password managers and the sign-in
/// and administrator prompts, the Windows key (it opens Run), and typing into a password field.
/// </summary>
internal sealed class ControlTools(Func<IntPtr> targetWindow)
{
    public const int MaxText = 2000, MaxPresses = 12;

    private const string Prefer =
        "Last resort: first use a direct tool when one fits (url_open for a page or a search, app_open, "
        + "browser_show_tab). Needs the person's PIN, or runs within an approval they opened with it. Give the "
        + "same task on every step of one job, and check with screen_read before the next step.";

    private static readonly Dictionary<string, ControlType[]> Roles = new(StringComparer.Ordinal)
    {
        ["button"] = [ControlType.Button, ControlType.SplitButton],
        ["link"] = [ControlType.Hyperlink],
        ["field"] = [ControlType.Edit, ControlType.ComboBox, ControlType.Document],
        ["checkbox"] = [ControlType.CheckBox, ControlType.RadioButton],
        ["tab"] = [ControlType.TabItem],
        ["menu"] = [ControlType.MenuItem],
        ["row"] = [ControlType.ListItem, ControlType.DataItem, ControlType.TreeItem],
    };

    public IEnumerable<DeviceTool> Tools() =>
    [
        new("pc_type",
            "Type text on this PC's keyboard into the field that has the cursor, in the window the person is in or in app. "
            + "Put the cursor there first with pc_click. Never types into a password field. " + Prefer,
            "control", 3,
            Step(new JsonObject
            {
                ["text"] = Schema.Text("Exactly what to type."),
                ["pressEnter"] = Schema.Flag("Press Enter after typing (to search or send a line)."),
            }, "text"),
            (args, ct) => Task.Run(() => Type(args), ct)),
        new("pc_keys",
            "Press keys or a keyboard shortcut on this PC, in the window the person is in or in app: e.g. 'ctrl+l', "
            + "'ctrl+shift+t', 'enter', 'esc', 'down down enter'. Up to 12 presses. Never the Windows key, and never in a "
            + "password field. " + Prefer,
            "control", 3,
            Step(new JsonObject
            {
                ["keys"] = Schema.Text("The presses in order, separated by spaces; + joins a shortcut's keys (ctrl, shift, alt)."),
            }, "keys"),
            (args, ct) => Task.Run(() => Keys(args), ct)),
        new("pc_click",
            "Click a button, link, tab, checkbox, menu item or row in the window the person is in or of app, found by "
            + "its label as shown on screen (or as read to screen readers); a field gets the cursor, ready for pc_type. "
            + "When several match, the answer says how many: say which with index. " + Prefer,
            "control", 3,
            Step(new JsonObject
            {
                ["label"] = Schema.Text("The control's label as shown, e.g. 'Search', 'Subscribe', 'Downloads'."),
                ["role"] = Schema.OneOf("The kind of control, to tell apart two with one label.", [.. Roles.Keys, "any"]),
                ["index"] = Schema.Integer("Which of several matches, 1 for the one nearest the top.", 1, 20),
            }, "label"),
            (args, ct) => Task.Run(() => Click(args, ct), ct)),
        new("pc_scroll",
            "Scroll the window the person is in or of app. " + Prefer,
            "control", 3,
            Step(new JsonObject
            {
                ["direction"] = Schema.OneOf("Which way the page should move into view.", ["up", "down", "left", "right"]),
                ["amount"] = Schema.Integer("How far, in steps of three lines (default 5).", 1, 30),
            }, "direction"),
            (args, ct) => Task.Run(() => Scroll(args), ct)),
    ];

    private static JsonObject Step(JsonObject properties, string required)
    {
        properties["app"] = Schema.Text("The app to do it in, by name or program (brought to the front first). Default: the window the person is in.");
        properties["task"] = Schema.Text("The whole job this step belongs to, the same on every step, e.g. 'play lofi music on YouTube'.");
        return Schema.Object(properties, required);
    }

    /// <summary>Why Ira must not act in this window, or null: the PC's own word, by program file.</summary>
    public static string? Refusal(WindowInfo window)
    {
        if (AppTools.IsNever(new AppTools.App(window.AppName, window.Program)))
            return "I never act in terminals, shells, Task Manager or the like: whatever is typed there runs as a command. Do it yourself";
        if (ScreenTools.NeverRead.TryGetValue(window.Program, out var known))
            return $"I never act in {known}: it holds passwords or asks for them. Do it yourself";
        if (ScreenTools.Refusal(window) is not null)
            return "Windows' desktop, taskbar or Start is in front. Name the app to act in, or bring it to the front";
        return null;
    }

    /// <summary>The window to act in, brought to the front: the one named in app, or the person's.</summary>
    private WindowInfo Front(ToolArgs args)
    {
        var named = args.Text("app", 80);
        var window = named is null ? WindowInfo.Of(targetWindow()) : Find(named);
        if (window is null) throw new ToolFailure(named is null ? "no window is open in front" : $"no window of {named} is open: open it with app_open first");
        if (Refusal(window) is { } refusal) throw new ToolFailure(refusal);
        Native.BringToFront(window.Handle);
        Thread.Sleep(150); // let it take the keyboard
        if (Native.GetForegroundWindow() != window.Handle) throw new ToolFailure($"{window.AppName} did not come to the front: try again");
        return window;
    }

    /// <summary>A visible top-level window whose program, app name or title has these words.</summary>
    private static WindowInfo? Find(string named)
    {
        var wanted = named.Trim();
        if (wanted.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) wanted = wanted[..^4];
        var windows = new List<WindowInfo>();
        foreach (AutomationElement element in AutomationElement.RootElement.FindAll(TreeScope.Children, Condition.TrueCondition))
        {
            var handle = new IntPtr(element.Current.NativeWindowHandle);
            if (handle == IntPtr.Zero || !Native.IsWindowVisible(handle)) continue;
            if (WindowInfo.Of(handle) is { } info) windows.Add(info);
        }
        bool Has(string text) => text.Contains(wanted, StringComparison.OrdinalIgnoreCase);
        return windows.FirstOrDefault(w => Path.GetFileNameWithoutExtension(w.Program).Equals(wanted, StringComparison.OrdinalIgnoreCase))
            ?? windows.FirstOrDefault(w => w.AppName.Equals(wanted, StringComparison.OrdinalIgnoreCase))
            ?? windows.FirstOrDefault(w => Has(w.AppName) || Has(w.Program))
            ?? windows.FirstOrDefault(w => Has(w.Title));
    }

    /// <summary>The control with the keyboard must be in this window and must not take a password.</summary>
    private static void CheckFocus(WindowInfo window)
    {
        AutomationElement? focused;
        try
        {
            focused = AutomationElement.FocusedElement;
        }
        catch (Exception e) when (e is ElementNotAvailableException or InvalidOperationException or COMException)
        {
            focused = null;
        }
        if (focused is null) return;
        if (focused.Current.IsPassword) throw new ToolFailure("the cursor is in a password field: I never type there. Type it yourself");
        Native.GetWindowThreadProcessId(window.Handle, out var pid);
        if (focused.Current.ProcessId != pid) throw new ToolFailure($"the keyboard is not in {window.AppName}: click the field first with pc_click");
    }

    private static JsonObject Done(WindowInfo window, string summary, JsonObject? more = null)
    {
        var result = more ?? new JsonObject();
        result["app"] = window.Program;
        result["summary"] = summary;
        return result;
    }

    // --- typing and keys ---------------------------------------------------------------

    private JsonNode Type(JsonObject raw)
    {
        var args = new ToolArgs(raw, "text", "pressEnter", "app", "task");
        var text = raw["text"] is JsonValue value && value.TryGetValue(out string? written) && written.Length > 0
            ? written
            : throw new ToolFailure("say what to type");
        if (text.Length > MaxText) throw new ToolFailure($"that is more than {MaxText} characters: type it in parts");
        var enter = args.Flag("pressEnter") ?? false;
        var window = Front(args);
        CheckFocus(window);
        Keyboard.Text(text);
        if (enter) Keyboard.Press([], Keyboard.VK_RETURN);
        return Done(window, $"Typed {text.Length} characters in {window.AppName}" + (enter ? " and pressed Enter." : "."));
    }

    private JsonNode Keys(JsonObject raw)
    {
        var args = new ToolArgs(raw, "keys", "app", "task");
        var presses = Keyboard.Parse(args.Required("keys", 200, "which keys to press"));
        var window = Front(args);
        CheckFocus(window);
        foreach (var (modifiers, key) in presses) Keyboard.Press(modifiers, key);
        return Done(window, $"Pressed {args.Text("keys", 200)} in {window.AppName}.");
    }

    // --- clicking ----------------------------------------------------------------------

    private JsonNode Click(JsonObject raw, CancellationToken ct)
    {
        var args = new ToolArgs(raw, "label", "role", "index", "app", "task");
        var label = args.Required("label", 200, "the label of what to click");
        var role = args.Text("role", 20) ?? "any";
        if (role != "any" && !Roles.ContainsKey(role)) throw new ToolFailure("role is one of " + string.Join(", ", Roles.Keys) + " or any");
        var index = args.Number("index", 1, 20);
        var window = Front(args);

        var found = Matches(AutomationElement.FromHandle(window.Handle), label, role, ct);
        if (found.Count == 0)
            throw new ToolFailure($"no control called “{label}” is in {window.AppName}'s window: read it with screen_read and use a label shown there");
        if (found.Count > 1 && index is null && found.Count(e => Same(e.Current.Name, label)) != 1)
        {
            return Done(window, $"{found.Count} controls in {window.AppName} match “{label}”: say which with index (1 is nearest the top).",
                new JsonObject { ["matches"] = found.Count });
        }
        var element = index is { } n
            ? n <= found.Count ? found[n - 1] : throw new ToolFailure($"only {found.Count} controls match “{label}”")
            : found.Count == 1 ? found[0] : found.First(e => Same(e.Current.Name, label));
        if (element.Current.IsPassword) throw new ToolFailure("that is a password field: I never act there. Type it yourself");
        Press(element);
        return Done(window, $"Clicked “{element.Current.Name}” in {window.AppName}.",
            new JsonObject { ["clicked"] = element.Current.Name, ["role"] = element.Current.ControlType.ProgrammaticName.Replace("ControlType.", "") });
    }

    private static bool Same(string name, string label) => name.Trim().Equals(label, StringComparison.OrdinalIgnoreCase);

    /// <summary>Controls on screen with this label (the exact name first), nearest the top first.</summary>
    private static List<AutomationElement> Matches(AutomationElement window, string label, string role, CancellationToken ct)
    {
        var types = role == "any" ? Roles.Values.SelectMany(t => t).ToHashSet() : Roles[role].ToHashSet();
        var found = new List<AutomationElement>();
        var queue = new Queue<AutomationElement>([window]);
        var seen = 0;
        while (queue.Count > 0 && seen++ < 5000)
        {
            ct.ThrowIfCancellationRequested();
            var element = queue.Dequeue();
            try
            {
                var current = element.Current;
                if (!current.IsOffscreen && current.IsEnabled && types.Contains(current.ControlType)
                    && current.Name.Contains(label, StringComparison.OrdinalIgnoreCase))
                {
                    found.Add(element);
                }
                for (var child = TreeWalker.ControlViewWalker.GetFirstChild(element); child is not null;
                     child = TreeWalker.ControlViewWalker.GetNextSibling(child))
                {
                    queue.Enqueue(child);
                }
            }
            catch (ElementNotAvailableException)
            {
                // it went away while we looked
            }
        }
        return [.. found
            .OrderBy(e => Same(e.Current.Name, label) ? 0 : 1)
            .ThenBy(e => e.Current.BoundingRectangle.Top)
            .ThenBy(e => e.Current.BoundingRectangle.Left)];
    }

    /// <summary>What a click does to this control, through UI Automation; the mouse only when it has no such action.</summary>
    private static void Press(AutomationElement element)
    {
        if (element.TryGetCurrentPattern(InvokePattern.Pattern, out var invoke)) ((InvokePattern)invoke).Invoke();
        else if (element.TryGetCurrentPattern(TogglePattern.Pattern, out var toggle)) ((TogglePattern)toggle).Toggle();
        else if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out var select)) ((SelectionItemPattern)select).Select();
        else if (element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out var expand))
        {
            var pattern = (ExpandCollapsePattern)expand;
            if (pattern.Current.ExpandCollapseState == ExpandCollapseState.Collapsed) pattern.Expand();
            else pattern.Collapse();
        }
        else if (element.Current.ControlType == ControlType.Edit || element.Current.ControlType == ControlType.Document)
            element.SetFocus();
        else if (element.TryGetClickablePoint(out var point)) Mouse.Click((int)point.X, (int)point.Y);
        else element.SetFocus();
    }

    // --- scrolling ---------------------------------------------------------------------

    private JsonNode Scroll(JsonObject raw)
    {
        var args = new ToolArgs(raw, "direction", "amount", "app", "task");
        var direction = args.Required("direction", 10, "which way to scroll: up, down, left or right");
        if (direction is not ("up" or "down" or "left" or "right")) throw new ToolFailure("direction is up, down, left or right");
        var amount = args.Number("amount", 1, 30) ?? 5;
        var window = Front(args);
        if (!Native.GetWindowRect(window.Handle, out var rect)) throw new ToolFailure("that window closed");
        Mouse.Wheel((rect.Left + rect.Right) / 2, (rect.Top + rect.Bottom) / 2, direction, amount);
        return Done(window, $"Scrolled {direction} in {window.AppName}.");
    }

    // --- input -------------------------------------------------------------------------

    /// <summary>Key presses as Windows sends them, and the names the model may use for keys.</summary>
    internal static class Keyboard
    {
        public const ushort VK_RETURN = 0x0D, VK_SHIFT = 0x10, VK_CONTROL = 0x11, VK_MENU = 0x12;

        private static readonly Dictionary<string, ushort> Named = new(StringComparer.OrdinalIgnoreCase)
        {
            ["enter"] = VK_RETURN, ["return"] = VK_RETURN, ["esc"] = 0x1B, ["escape"] = 0x1B, ["tab"] = 0x09,
            ["space"] = 0x20, ["backspace"] = 0x08, ["delete"] = 0x2E, ["del"] = 0x2E, ["insert"] = 0x2D,
            ["up"] = 0x26, ["down"] = 0x28, ["left"] = 0x25, ["right"] = 0x27, ["home"] = 0x24, ["end"] = 0x23,
            ["pageup"] = 0x21, ["pagedown"] = 0x22,
        };

        private static readonly Dictionary<string, ushort> Modifiers = new(StringComparer.OrdinalIgnoreCase)
        {
            ["ctrl"] = VK_CONTROL, ["control"] = VK_CONTROL, ["shift"] = VK_SHIFT, ["alt"] = VK_MENU,
        };

        /// <summary>"ctrl+l down enter" as presses; refuses the Windows key and the shortcuts that reach a command.</summary>
        public static List<(ushort[] Modifiers, ushort Key)> Parse(string keys)
        {
            var presses = new List<(ushort[], ushort)>();
            foreach (var press in keys.Split(' ', StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = press.Split('+', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length == 0) continue;
                var held = new List<ushort>();
                foreach (var part in parts[..^1])
                {
                    if (part.ToLowerInvariant() is "win" or "windows" or "meta" or "super" or "cmd" or "command")
                        throw new ToolFailure("I never press the Windows key: it opens Run and the like. Use ctrl, alt or shift");
                    held.Add(Modifiers.TryGetValue(part, out var modifier) ? modifier : throw new ToolFailure($"“{part}” is not a key I hold: use ctrl, alt or shift"));
                }
                var key = Key(parts[^1]);
                var name = string.Join("+", parts.Select(p => p.ToLowerInvariant()));
                // Task Manager, the security screen, and switching to some other app unseen.
                if (held.Contains(VK_CONTROL) && held.Contains(VK_SHIFT) && key == 0x1B
                    || held.Contains(VK_CONTROL) && held.Contains(VK_MENU) && key == 0x2E
                    || held.Contains(VK_MENU) && key is 0x09 or 0x1B)
                {
                    throw new ToolFailure($"I never press {name}: name the app to act in instead");
                }
                presses.Add((held.ToArray(), key));
            }
            if (presses.Count == 0) throw new ToolFailure("say which keys to press");
            if (presses.Count > MaxPresses) throw new ToolFailure($"that is more than {MaxPresses} presses: do it in parts");
            return presses;
        }

        private static ushort Key(string name)
        {
            if (name.ToLowerInvariant() is "win" or "windows" or "meta" or "super" or "cmd" or "command")
                throw new ToolFailure("I never press the Windows key: it opens Run and the like. Use ctrl, alt or shift");
            if (Named.TryGetValue(name, out var named)) return named;
            if (name.Length == 1 && char.IsAsciiLetterOrDigit(name[0])) return char.ToUpperInvariant(name[0]);
            if (name.Length is 2 or 3 && (name[0] is 'f' or 'F') && int.TryParse(name[1..], out var f) && f is >= 1 and <= 12)
                return (ushort)(0x6F + f);
            throw new ToolFailure($"“{name}” is not a key I know: use letters, digits, f1 to f12, enter, esc, tab, space, backspace, delete, arrows, home, end, pageup or pagedown");
        }

        public static void Press(ushort[] modifiers, ushort key)
        {
            var inputs = new List<INPUT>();
            inputs.AddRange(modifiers.Select(m => KeyInput(m, 0, up: false)));
            inputs.Add(KeyInput(key, 0, up: false));
            inputs.Add(KeyInput(key, 0, up: true));
            inputs.AddRange(Enumerable.Reverse(modifiers).Select(m => KeyInput(m, 0, up: true)));
            Send(inputs);
        }

        /// <summary>Text as Unicode key presses, so any language types as written; a line break presses Enter.</summary>
        public static void Text(string text)
        {
            var inputs = new List<INPUT>();
            foreach (var c in text.Replace("\r\n", "\n"))
            {
                if (c == '\n')
                {
                    inputs.Add(KeyInput(VK_RETURN, 0, up: false));
                    inputs.Add(KeyInput(VK_RETURN, 0, up: true));
                    continue;
                }
                inputs.Add(KeyInput(0, c, up: false, unicode: true));
                inputs.Add(KeyInput(0, c, up: true, unicode: true));
            }
            Send(inputs);
        }

        private static INPUT KeyInput(ushort vk, ushort scan, bool up, bool unicode = false) => new()
        {
            Type = 1, // INPUT_KEYBOARD
            U = new InputUnion
            {
                Keyboard = new KEYBDINPUT
                {
                    Vk = vk,
                    Scan = scan,
                    Flags = (up ? 0x0002u : 0) | (unicode ? 0x0004u : 0), // KEYEVENTF_KEYUP, KEYEVENTF_UNICODE
                },
            },
        };
    }

    internal static class Mouse
    {
        public static void Click(int x, int y)
        {
            SetCursorPos(x, y);
            Send([MouseInput(0x0002, 0), MouseInput(0x0004, 0)]); // left down, left up
        }

        public static void Wheel(int x, int y, string direction, int steps)
        {
            SetCursorPos(x, y);
            var flag = direction is "left" or "right" ? 0x01000u : 0x0800u; // MOUSEEVENTF_HWHEEL, MOUSEEVENTF_WHEEL
            // One notch (120) scrolls three lines; up and right are positive.
            var delta = (direction is "up" or "right" ? 1 : -1) * 120;
            Send([.. Enumerable.Repeat(MouseInput(flag, delta), steps)]);
        }

        private static INPUT MouseInput(uint flags, int data) => new()
        {
            Type = 0, // INPUT_MOUSE
            U = new InputUnion { Mouse = new MOUSEINPUT { MouseData = unchecked((uint)data), Flags = flags } },
        };
    }

    private static void Send(List<INPUT> inputs)
    {
        if (inputs.Count == 0) return;
        var sent = SendInput((uint)inputs.Count, [.. inputs], Marshal.SizeOf<INPUT>());
        if (sent != inputs.Count) throw new ToolFailure("Windows did not take the input (an administrator's window may be in front)");
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct INPUT
    {
        public uint Type;
        public InputUnion U;
    }

    [StructLayout(LayoutKind.Explicit)]
    internal struct InputUnion
    {
        [FieldOffset(0)] public MOUSEINPUT Mouse;
        [FieldOffset(0)] public KEYBDINPUT Keyboard;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MOUSEINPUT
    {
        public int Dx, Dy;
        public uint MouseData, Flags, Time;
        public IntPtr ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct KEYBDINPUT
    {
        public ushort Vk, Scan;
        public uint Flags, Time;
        public IntPtr ExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint count, INPUT[] inputs, int size);

    [DllImport("user32.dll")]
    private static extern bool SetCursorPos(int x, int y);
}
