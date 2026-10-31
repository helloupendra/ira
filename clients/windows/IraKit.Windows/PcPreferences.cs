using System.Security.Cryptography;
using System.Text.Json;
using IraKit.Tools;

namespace IraKit;

/// <summary>The shortcut that opens Ira's panel: one of the few Settings offers.</summary>
public sealed record Shortcut(string Name, uint Modifiers, uint Key)
{
    public const uint Alt = 0x1, Control = 0x2, Shift = 0x4;

    public static readonly IReadOnlyList<Shortcut> Choices =
    [
        new("Ctrl+Alt+Space", Control | Alt, 0x20),
        new("Ctrl+Shift+Space", Control | Shift, 0x20),
        new("Alt+Shift+Space", Alt | Shift, 0x20),
        new("Ctrl+Alt+I", Control | Alt, 0x49),
    ];

    public static Shortcut Default => Choices[0];

    /// <summary>The choice by its name, or the default for a name it does not know.</summary>
    public static Shortcut Named(string? name) => Choices.FirstOrDefault(c => c.Name == name) ?? Default;
}

/// <summary>
/// How the person set Ira up on this PC, apart from the pairing (so pairing again keeps it):
/// the shortcut that opens the panel and the folders Ira may use.
/// </summary>
public sealed record PcPreferences
{
    public string Shortcut { get; init; } = IraKit.Shortcut.Default.Name;

    /// <summary>
    /// Folders inside the user's folder narrow Ira to them; folders elsewhere (another drive,
    /// say) are added. None: the user's folder.
    /// </summary>
    public IReadOnlyList<string> Folders { get; init; } = [];

    /// <summary>
    /// What the routine skill salts a network's code with, made once on this PC and kept, so a
    /// network named on your Ira keeps its name; empty until first needed.
    /// </summary>
    public string NetworkSalt { get; init; } = "";

    /// <summary>These preferences with a salt, made now if there was none.</summary>
    public PcPreferences WithSalt() =>
        NetworkSalt.Length > 0 ? this : this with { NetworkSalt = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16)) };

    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Ira", "preferences.json");

    public PathPolicy Policy(string? home = null) =>
        PathPolicy.ForFolders(home ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), Folders);

    public static PcPreferences Load(string? path = null)
    {
        path ??= DefaultPath;
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<PcPreferences>(File.ReadAllText(path), Json.Options) ?? new() : new();
        }
        catch (JsonException)
        {
            return new(); // a damaged file: the defaults
        }
    }

    public void Save(string? path = null)
    {
        path ??= DefaultPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(this, Json.Options));
        File.Move(temp, path, overwrite: true);
    }
}
